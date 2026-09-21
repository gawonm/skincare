"""LangGraph 각 단계의 상태 전이를 구현한다."""

from datetime import UTC, datetime

from agent.context import ContextBuilder
from agent.evidence_query_policy import EvidenceQueryPolicy
from agent.ports import IngredientRepository, LlmClient, ProductRepository, RoutinePlanner
from agent.prompts import PromptCatalog, PromptPurpose, PromptRequest
from agent.rag.claim_schemas import (
    IngredientRecommendationCandidate,
    RecommendationBasis,
    RecommendationProductMatch,
)
from agent.rag.retrieval.ingredient_alias_mapper import CommonIngredientAliasMapper
from agent.rag.retrieval.product_filter_validator import ProductFilterValidator
from agent.rag.schemas import (
    EvidenceConditions,
    IngredientResolveRequest,
    LookupStatus,
    ProductCandidate,
    ProductCandidateSet,
    ProductGetRequest,
    ProductRecord,
    ProductSearchFilters,
    ProductSearchRequest,
    ProductTaxonomy,
    RoutinePlan,
    RoutinePlanRequest,
    RoutineValidationRequest,
    Weekday,
)
from agent.rag_route_policy import RagRoutePolicy
from agent.runtime import AgentRuntime
from agent.schemas import (
    AgentState,
    ChatMessage,
    ChatStatus,
    ChatTurnInput,
    ChatTurnOutput,
    GraphNode,
    Intent,
    MessageRole,
    ParsedRequest,
    PendingQuestion,
    RagRoute,
    ResolvedEntities,
    RoutineSaveHandoff,
    SessionSnapshot,
    SourcedValue,
    UnderstandingRequest,
    UnresolvedItem,
    UnresolvedKind,
    ValueOrigin,
)
from agent.task_planning import TaskPlanBuilder

DEMO_RESULT_NOTICE = "개발용 fixture 결과이며 실제 제품·임상 검증 결과가 아닙니다."
PRODUCT_TARGET_QUESTION = "루틴에 사용할 제품명을 알려주세요."
EVIDENCE_TARGET_QUESTION = "설명할 성분이나 비교할 두 제품을 구체적으로 알려주세요."
CANDIDATE_REFERENCE_QUESTION = (
    "참조한 후보 번호를 현재 목록에서 찾을 수 없습니다. 번호를 다시 알려주세요."
)
ROUTINE_REFERENCE_QUESTION = "참조한 루틴 버전을 현재 방에서 찾을 수 없습니다. 다시 선택해 주세요."
NO_RESULT_MESSAGE = "현재 상품 데이터에서 조건을 만족하는 제품을 찾지 못했습니다."
EVIDENCE_PRODUCT_LIMITATION = "성분 근거이며 완제품 자체의 임상 효과를 입증하지 않습니다."
CLAIM_ONLY_PRODUCT_LIMITATION = "현재 연결된 공인 근거로 Claim을 충분히 확인하지 못했습니다."


class AgentNodes:
    """주입된 포트만 사용해 그래프 노드를 실행한다."""

    _EVIDENCE_REFERENCES = ("이 성분", "그 성분", "해당 성분", "이 제품", "그 제품")

    def __init__(
        self,
        llm: LlmClient,
        product_repository: ProductRepository,
        ingredient_repository: IngredientRepository,
        routine_planner: RoutinePlanner,
        context_builder: ContextBuilder,
        prompt_catalog: PromptCatalog,
        product_taxonomy: ProductTaxonomy,
        runtime: AgentRuntime,
        task_plan: TaskPlanBuilder,
        rag_route_policy: RagRoutePolicy,
        evidence_query_policy: EvidenceQueryPolicy,
    ) -> None:
        self._llm = llm
        self._product_repository = product_repository
        self._ingredient_repository = ingredient_repository
        self._routine_planner = routine_planner
        self._context_builder = context_builder
        self._prompt_catalog = prompt_catalog
        self._product_taxonomy = product_taxonomy.model_copy(deep=True)
        self._product_filters = ProductFilterValidator(self._product_taxonomy)
        self._ingredient_aliases = CommonIngredientAliasMapper()
        self._runtime = runtime
        self._task_plan = task_plan
        self._rag_route_policy = rag_route_policy
        self._evidence_query_policy = evidence_query_policy

    async def prepare_turn(self, state: AgentState) -> AgentState:
        self._require_turn_fields(state)
        snapshot = state.restored_snapshot or SessionSnapshot()
        # 히스토리의 완료 스냅샷을 기준으로 삼아 실패한 실행의 체크포인트가
        # 다음 요청 상태를 앞질러 가지 못하게 한다.
        state.messages = [message.model_copy(deep=True) for message in snapshot.messages]
        state.profile = snapshot.profile.model_copy(deep=True)
        state.task_context = snapshot.task_context.model_copy(deep=True)
        state.pending_question = (
            snapshot.pending_question.model_copy(deep=True) if snapshot.pending_question else None
        )
        state.candidate_set = (
            snapshot.candidate_set.model_copy(deep=True) if snapshot.candidate_set else None
        )
        state.routine = snapshot.routine.model_copy(deep=True) if snapshot.routine else None
        state.evidence = []
        state.summary = snapshot.summary.model_copy(deep=True) if snapshot.summary else None
        # 복구용 스냅샷을 상태 안에 다시 중첩 저장하면 체크포인트 크기만 커진다.
        state.restored_snapshot = None

        state.parsed_request = None
        state.resolved_entities = ResolvedEntities()
        state.rag_route = None
        state.case_bundle = None
        state.case_claim_bundle = None
        state.claim_bundle = None
        state.claim_verification_bundle = None
        state.recommendation_ingredients = None
        state.evidence_bundle = None
        state.task_queue = []
        state.current_intent = None
        state.artifacts = []
        state.citations = []
        state.unresolved = []
        state.response_parts = []
        state.follow_up_question = None
        state.status = ChatStatus.COMPLETED
        state.error_code = None
        state.retryable = False
        state.tool_call_count = 0
        state.revision_count = 0
        state.needs_revision = False
        state.started_at = datetime.now(UTC)
        state.events = []
        state.output = None
        state.save_handoff = None

        identifiers = state.identifiers
        turn = state.turn_input
        if identifiers is None or turn is None:
            raise RuntimeError("그래프 호출에 요청 식별자 또는 사용자 입력이 없습니다.")
        if not any(message.message_id == identifiers.user_message_id for message in state.messages):
            state.messages.append(
                state.user_message.model_copy(deep=True)
                if state.user_message
                else ChatMessage(
                    message_id=identifiers.user_message_id,
                    request_id=turn.request_id,
                    role=MessageRole.USER,
                    content=turn.message,
                    sequence=self._next_sequence(state),
                )
            )
        self._record_event(state, GraphNode.PREPARE_TURN, "이번 요청 필드를 초기화했습니다.")
        return state

    async def understand_request(self, state: AgentState) -> AgentState:
        turn = self._require_turn(state)
        context = self._context_builder.build(state)
        state.summary = context.summary
        prompt = self._prompt_catalog.get(PromptRequest(purpose=PromptPurpose.UNDERSTAND_REQUEST))
        state.parsed_request = await self._llm.understand(
            UnderstandingRequest(
                message=turn.message,
                system_prompt=prompt.system_message,
                context=context,
                product_taxonomy=self._product_taxonomy.model_copy(deep=True),
            )
        )
        parsed = state.parsed_request
        pending = state.pending_question
        if parsed.pending_answer and pending and pending.original_request:
            original = pending.original_request
            parsed = parsed.model_copy(
                update={
                    "query": original.query + "\n" + parsed.query,
                    "intents": original.intents,
                    "rag_route": original.rag_route or parsed.rag_route,
                    "category": parsed.category or original.category,
                    "texture": parsed.texture or original.texture,
                    "skin_feel": parsed.skin_feel or original.skin_feel,
                    "unsupported_product_conditions": list(
                        dict.fromkeys(
                            original.unsupported_product_conditions
                            + parsed.unsupported_product_conditions
                        )
                    ),
                    "ingredient_mentions": list(
                        dict.fromkeys(
                            (
                                original.ingredient_mentions
                                if pending.target_field != "ingredient_name"
                                else []
                            )
                            + (
                                parsed.ingredient_mentions
                                or (
                                    [parsed.query]
                                    if pending.target_field == "ingredient_name"
                                    else []
                                )
                            )
                        )
                    ),
                    "known_conditions": EvidenceConditions.model_validate(
                        {
                            **original.known_conditions.model_dump(exclude_none=True),
                            **parsed.known_conditions.model_dump(exclude_none=True),
                        }
                    ),
                    "excluded_weekdays": list(
                        dict.fromkeys(original.excluded_weekdays + parsed.excluded_weekdays)
                    ),
                }
            )
        elif not parsed.pending_answer:
            state.pending_question = None
        if Intent.PRODUCT_DISCOVERY in parsed.intents:
            if parsed.is_modification or parsed.pending_answer:
                filters = state.task_context.search_filters
                parsed.category = parsed.category or filters.category
                parsed.texture = parsed.texture or filters.texture
                parsed.skin_feel = parsed.skin_feel or filters.skin_feel
            else:
                state.task_context.search_filters = ProductSearchFilters()
                state.task_context.rejected_product_ids = []
        validated_filters = self._product_filters.normalize(
            ProductSearchFilters(
                category=parsed.category, texture=parsed.texture, skin_feel=parsed.skin_feel
            )
        )
        parsed.category = validated_filters.filters.category
        parsed.texture = validated_filters.filters.texture
        parsed.skin_feel = validated_filters.filters.skin_feel
        parsed.unsupported_product_conditions = list(
            dict.fromkeys(
                parsed.unsupported_product_conditions + validated_filters.unsupported_conditions
            )
        )
        state.parsed_request = parsed
        state.task_context.excluded_weekdays = list(
            dict.fromkeys(state.task_context.excluded_weekdays + parsed.excluded_weekdays)
        )
        known_experiences = {experience.value for experience in state.profile.experiences}
        state.profile.experiences.extend(
            SourcedValue(value=experience, origin=ValueOrigin.USER)
            for experience in state.parsed_request.reported_experiences
            if experience not in known_experiences
        )
        self._record_event(state, GraphNode.UNDERSTAND_REQUEST, "목적과 조건을 추출했습니다.")
        return state

    async def decide_rag_route(self, state: AgentState) -> AgentState:
        parsed = self._require_parsed(state)
        decision = self._rag_route_policy.decide(parsed)
        state.parsed_request = parsed.model_copy(
            deep=True,
            update={
                "intents": decision.normalized_intents,
                "rag_route": decision.route,
                "skin_concerns": decision.normalized_skin_concerns or parsed.skin_concerns,
            },
        )
        state.rag_route = decision.route
        state.task_queue = self._task_plan.build(state.parsed_request)
        self._record_event(
            state,
            GraphNode.DECIDE_RAG_ROUTE,
            f"RAG 경로를 규칙으로 확정했습니다: {decision.reason.value}",
        )
        return state

    async def resolve_entities(self, state: AgentState) -> AgentState:
        parsed = self._require_parsed(state)
        ingredient_ids: list[str] = []
        products: list[ProductRecord] = []

        if not any(
            intent in parsed.intents
            for intent in (
                Intent.PRODUCT_DISCOVERY,
                Intent.ROUTINE_PLANNING,
                Intent.EVIDENCE_QA,
            )
        ):
            return state

        unresolved_names: list[str] = []
        # 상품 필터 문장 전체를 성분명으로 조회하면 DB 결과에 따라 우연히 성분이 붙을 수 있으므로,
        # Evidence 직행 질문에서만 원문을 보수적인 해석 후보로 사용한다.
        fallback_mentions = (
            [parsed.query]
            if not parsed.ingredient_mentions and parsed.rag_route is RagRoute.EVIDENCE_ONLY
            else []
        )
        for mention in parsed.ingredient_mentions or fallback_mentions:
            if not self._reserve_tool_call(state, GraphNode.RESOLVE_ENTITIES):
                break
            ingredient_result = await self._ingredient_repository.resolve(
                self._ingredient_request(mention)
            )
            alias_request = self._ingredient_aliases.map_request(self._ingredient_request(mention))
            if (
                ingredient_result.status is LookupStatus.NO_RESULTS
                and alias_request.name != mention
            ):
                if not self._reserve_tool_call(state, GraphNode.RESOLVE_ENTITIES):
                    break
                # DB의 원문 식별·모호성·오류를 별칭으로 덮어쓰지 않고 무결과일 때만 재조회한다.
                ingredient_result = self._ingredient_aliases.validate_result(
                    alias_request, await self._ingredient_repository.resolve(alias_request)
                )
            if ingredient_result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
                self._add_tool_failure(
                    state,
                    ingredient_result.error_message
                    or f"성분 조회를 수행하지 못했습니다: {mention} ({ingredient_result.status.value})",
                )
            elif ingredient_result.ambiguous_candidates:
                unresolved_names.append(mention)
            elif ingredient_result.status is LookupStatus.SUCCESS and ingredient_result.ingredient:
                ingredient_ids.append(ingredient_result.ingredient.ingredient_id)
            elif parsed.ingredient_mentions:
                unresolved_names.append(mention)

        needs_products = any(
            intent in parsed.intents
            for intent in (Intent.PRODUCT_DISCOVERY, Intent.ROUTINE_PLANNING)
        ) or (
            Intent.EVIDENCE_QA in parsed.intents
            and ("제품" in parsed.query or parsed.category is not None)
        )
        defer_product_search = (
            parsed.rag_route is RagRoute.CLAIM_THEN_EVIDENCE
            and Intent.PRODUCT_DISCOVERY in parsed.intents
        )
        if (
            needs_products
            and not defer_product_search
            and not unresolved_names
            and not parsed.unsupported_product_conditions
        ):
            product_entities = await self._search_products(
                state,
                ingredient_ids,
                GraphNode.RESOLVE_ENTITIES,
            )
            products = product_entities.products
            ingredient_ids = product_entities.ingredient_ids

        state.resolved_entities = ResolvedEntities(
            products=products,
            ingredient_ids=list(dict.fromkeys(ingredient_ids)),
            unresolved_names=unresolved_names,
        )
        self._record_event(state, GraphNode.RESOLVE_ENTITIES, "성분과 제품 식별을 마쳤습니다.")
        return state

    async def assess_information(self, state: AgentState) -> AgentState:
        parsed = self._require_parsed(state)
        question: str | None = None
        target_field: str | None = None
        reason: str | None = None
        turn = self._require_turn(state)

        if Intent.CLARIFICATION in parsed.intents:
            question = "성분 확인, 상품 추천, 루틴 만들기 중 어떤 도움이 필요한가요?"
            target_field = "intent"
            reason = "질문 목적을 추측해서 다른 작업을 실행하지 않습니다."
        elif self._evidence_query_policy.requires_clarification(state):
            question = "성분명을 하나의 후보로 식별하지 못했습니다. 정확한 표시 명칭을 알려주세요."
            target_field = "ingredient_name"
            reason = "모호한 후보들을 서로 다른 확정 성분으로 취급하면 안 됩니다."

        if turn.candidate_set_id is not None and (
            state.candidate_set is None
            or state.candidate_set.candidate_set_id != turn.candidate_set_id
        ):
            question = CANDIDATE_REFERENCE_QUESTION
            target_field = "candidate_set_id"
            reason = "다른 방이나 오래된 후보 목록을 현재 선택으로 사용하면 안 됩니다."

        if (
            question is None
            and turn.routine_version is not None
            and (state.routine is None or state.routine.version != turn.routine_version)
        ):
            question = ROUTINE_REFERENCE_QUESTION
            target_field = "routine_version"
            reason = "현재 계획과 다른 버전을 임의로 수정하면 변경 사항을 잃을 수 있습니다."

        if question is None and parsed.referenced_candidate_number is not None:
            candidate = self._candidate_by_rank(state, parsed.referenced_candidate_number)
            if candidate is None:
                question = CANDIDATE_REFERENCE_QUESTION
                target_field = "candidate_reference"
                reason = "후보 번호를 추측하면 다른 제품을 선택할 수 있습니다."

        if question is None and Intent.ROUTINE_PLANNING in parsed.intents:
            has_products = bool(state.resolved_entities.products)
            has_reference = (
                parsed.referenced_candidate_number is not None
                and parsed.referenced_candidate_number not in parsed.rejected_candidate_numbers
            )
            has_current_routine = state.routine is not None
            if (
                not has_products
                and not has_reference
                and not has_current_routine
                and parsed.rag_route is not RagRoute.CLAIM_THEN_EVIDENCE
            ):
                question = PRODUCT_TARGET_QUESTION
                target_field = "routine_products"
                reason = "제품이 식별되지 않으면 제품별 사용 계획을 만들 수 없습니다."

        demonstrative_query = any(word in parsed.query for word in self._EVIDENCE_REFERENCES)
        if (
            question is None
            and Intent.EVIDENCE_QA in parsed.intents
            and demonstrative_query
            and not state.resolved_entities.ingredient_ids
            and not state.resolved_entities.products
            and parsed.referenced_candidate_number is None
            and not state.task_context.evidence_target_ids
        ):
            question = EVIDENCE_TARGET_QUESTION
            target_field = "evidence_subject"
            reason = "대상을 추측하면 관련 없는 근거를 적용할 수 있습니다."

        if question and target_field and reason:
            state.follow_up_question = question
            state.pending_question = PendingQuestion(
                question_id=self._stable_id(state, "question"),
                question=question,
                target_field=target_field,
                reason=reason,
                original_intents=parsed.intents,
                original_request=parsed.model_copy(deep=True),
            )
        elif parsed.pending_answer:
            state.pending_question = None

        self._record_event(state, GraphNode.ASSESS_INFORMATION, "추가 정보 필요성을 판단했습니다.")
        return state

    async def ask_user(self, state: AgentState) -> AgentState:
        if not state.follow_up_question:
            raise RuntimeError("질문 노드에 후속 질문이 없습니다.")
        state.status = ChatStatus.NEEDS_INPUT
        state.response_parts = [state.follow_up_question]
        self._record_event(state, GraphNode.ASK_USER, "사용자 입력 대기로 정상 종료합니다.")
        return state

    async def route_task(self, state: AgentState) -> AgentState:
        if state.current_intent is None and state.task_queue:
            state.current_intent = state.task_queue.pop(0)
        self._record_event(state, GraphNode.ROUTE_TASK, "다음 작업을 선택했습니다.")
        return state

    async def process_task(self, state: AgentState) -> AgentState:
        if self._execution_limit_reached(state):
            state.current_intent = None
            state.task_queue = []
            return state

        intent = state.current_intent
        if intent is Intent.PRODUCT_DISCOVERY:
            await self._process_product_discovery(state)
        elif intent is Intent.ROUTINE_PLANNING:
            await self._process_routine(state)
        elif intent is Intent.GENERAL_CHAT:
            state.response_parts.append(
                "현재 결과를 유지합니다. 성분 확인·상품 검색·루틴 구성을 도와드릴 수 있어요."
            )
        elif intent is Intent.OUT_OF_SCOPE:
            state.response_parts.append(
                "기초화장품의 성분 확인, 상품 검색, 사용 루틴에 관한 질문을 해주세요."
            )
        elif intent is Intent.ROUTINE_SAVE:
            parsed = self._require_parsed(state)
            if Intent.ROUTINE_PLANNING in parsed.intents and not any(
                isinstance(artifact, RoutinePlan) for artifact in state.artifacts
            ):
                state.status = ChatStatus.PARTIAL
                state.response_parts.append(
                    "루틴 변경을 검증하지 못해 저장 요청을 만들지 않았습니다."
                )
            elif state.routine is None:
                state.status = ChatStatus.NEEDS_INPUT
                state.follow_up_question = (
                    "저장할 루틴이 없습니다. 먼저 사용할 제품으로 루틴을 만들어 주세요."
                )
                state.response_parts.append(state.follow_up_question)
            else:
                state.save_handoff = RoutineSaveHandoff(
                    routine_id=state.routine.routine_id,
                    version=state.routine.version,
                    is_demo=state.routine.is_demo,
                )
                state.response_parts.append(
                    "현재 루틴 버전의 저장 요청을 준비했습니다. 실제 저장은 로그인·권한 확인 후 백엔드에서 처리해야 합니다."
                )
        else:
            raise RuntimeError("실행할 Intent가 지정되지 않았습니다.")
        state.current_intent = None
        self._record_event(state, GraphNode.PROCESS_TASK, f"{intent.value} 작업을 실행했습니다.")
        return state

    async def validate_result(self, state: AgentState) -> AgentState:
        evidence_ids = {record.evidence_id for record in state.evidence}
        missing_citations = [
            citation.evidence_id
            for citation in state.citations
            if citation.evidence_id not in evidence_ids
        ]
        state.needs_revision = bool(missing_citations)
        if missing_citations:
            state.unresolved.append(
                UnresolvedItem(
                    kind=UnresolvedKind.CONFLICT,
                    detail="저장된 근거와 연결되지 않는 인용이 있어 제거가 필요합니다.",
                )
            )
        if not state.response_parts and state.status is ChatStatus.COMPLETED:
            state.status = ChatStatus.PARTIAL
            state.response_parts.append("완성할 수 있는 결과가 없습니다.")
        self._record_event(state, GraphNode.VALIDATE_RESULT, "인용과 결과 구조를 검증했습니다.")
        return state

    async def revise_result(self, state: AgentState) -> AgentState:
        evidence_ids = {record.evidence_id for record in state.evidence}
        state.citations = [
            citation for citation in state.citations if citation.evidence_id in evidence_ids
        ]
        state.revision_count += 1
        state.needs_revision = False
        self._record_event(state, GraphNode.REVISE_RESULT, "검증 실패 항목을 제거했습니다.")
        return state

    async def finalize_response(self, state: AgentState) -> AgentState:
        turn = self._require_turn(state)
        identifiers = state.identifiers
        if identifiers is None:
            raise RuntimeError("최종 응답에 assistant 메시지 식별자가 없습니다.")

        parts = list(state.response_parts)
        if (
            any(artifact.is_demo for artifact in state.artifacts)
            and DEMO_RESULT_NOTICE not in parts
        ):
            parts.append(DEMO_RESULT_NOTICE)
        message = "\n\n".join(parts)
        output = ChatTurnOutput(
            chat_room_id=turn.chat_room_id,
            request_id=turn.request_id,
            assistant_message_id=identifiers.assistant_message_id,
            status=state.status,
            message=message,
            intents=state.parsed_request.intents if state.parsed_request else [],
            follow_up_question=state.follow_up_question,
            artifacts=state.artifacts,
            citations=state.citations,
            unresolved=state.unresolved,
            error_code=state.error_code,
            retryable=state.retryable,
            save_handoff=state.save_handoff,
        )
        state.output = output
        if not any(
            existing.message_id == identifiers.assistant_message_id for existing in state.messages
        ):
            state.messages.append(
                ChatMessage(
                    message_id=identifiers.assistant_message_id,
                    request_id=turn.request_id,
                    role=MessageRole.ASSISTANT,
                    content=message,
                    sequence=self._next_sequence(state),
                )
            )
        self._context_builder.compact(state)
        self._record_event(state, GraphNode.FINALIZE_RESPONSE, "구조화된 응답을 만들었습니다.")
        return state

    async def _process_product_discovery(self, state: AgentState) -> None:
        parsed = self._require_parsed(state)
        if parsed.unsupported_product_conditions:
            state.status = ChatStatus.PARTIAL
            state.unresolved.extend(
                UnresolvedItem(kind=UnresolvedKind.UNSUPPORTED_CONDITION, detail=condition)
                for condition in parsed.unsupported_product_conditions
            )
            state.response_parts.append("요청한 상품 조건을 현재 지원 목록으로 처리할 수 없습니다.")
            return
        rejected_product_ids = {
            candidate.product.product_id
            for rank in parsed.rejected_candidate_numbers
            if (candidate := self._candidate_by_rank(state, rank)) is not None
        }
        state.task_context.rejected_product_ids = list(
            dict.fromkeys(state.task_context.rejected_product_ids + list(rejected_product_ids))
        )
        recommendation_matches: list[RecommendationProductMatch] = []
        if parsed.rag_route is RagRoute.CLAIM_THEN_EVIDENCE:
            recommendation_matches = await self._search_recommendation_products(state)
            products = [match.product for match in recommendation_matches]
        else:
            products = list(state.resolved_entities.products)
        products = [
            product
            for product in products
            if product.product_id not in state.task_context.rejected_product_ids
        ]
        if recommendation_matches:
            allowed_product_ids = {product.product_id for product in products}
            recommendation_matches = [
                match
                for match in recommendation_matches
                if match.product.product_id in allowed_product_ids
            ]
        if not products:
            state.status = ChatStatus.PARTIAL
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=NO_RESULT_MESSAGE)
            )
            state.response_parts.append(NO_RESULT_MESSAGE)
            return

        if recommendation_matches:
            state.resolved_entities = state.resolved_entities.model_copy(
                deep=True,
                update={
                    "products": products,
                    "ingredient_ids": [
                        candidate.ingredient_id
                        for candidate in (state.recommendation_ingredients.candidates)
                    ]
                    if state.recommendation_ingredients is not None
                    else [],
                },
            )

        candidates = (
            self._recommendation_product_candidates(state, recommendation_matches)
            if recommendation_matches
            else [
                ProductCandidate(
                    rank=rank,
                    product=product,
                    reasons=self._candidate_reasons(state.task_context.search_filters),
                    unresolved=self._product_limitations(product),
                )
                for rank, product in enumerate(products, start=1)
            ]
        )
        candidate_set = ProductCandidateSet(
            candidate_set_id=self._stable_id(state, "candidates"),
            candidates=candidates,
            is_demo=any(product.is_demo for product in products),
        )
        state.candidate_set = candidate_set
        state.artifacts.append(candidate_set)
        if recommendation_matches:
            self._append_recommendation_product_message(state, candidates, recommendation_matches)
        else:
            lines = [f"{candidate.rank}번. {candidate.product.name}" for candidate in candidates]
            title = "개발용 제품 후보:" if candidate_set.is_demo else "조건에 맞는 제품 후보:"
            state.response_parts.append(title + "\n" + "\n".join(lines))

    async def _search_recommendation_products(
        self,
        state: AgentState,
    ) -> list[RecommendationProductMatch]:
        recommendation_set = state.recommendation_ingredients
        if recommendation_set is None:
            return []
        matches: dict[str, RecommendationProductMatch] = {}
        ingredient_ids = [candidate.ingredient_id for candidate in recommendation_set.candidates]
        for candidate in recommendation_set.candidates:
            unresolved_count = len(state.unresolved)
            previous_error_code = state.error_code
            entities = await self._search_products(
                state,
                [candidate.ingredient_id],
                GraphNode.PROCESS_TASK,
            )
            if not entities.products:
                if (
                    len(state.unresolved) == unresolved_count
                    and state.error_code is previous_error_code
                ):
                    state.status = ChatStatus.PARTIAL
                    detail = (
                        "추천 성분과 연결된 상품을 찾지 못했습니다: "
                        f"{candidate.ingredient_id}"
                    )
                    state.unresolved.append(
                        UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=detail)
                    )
                continue
            for product in entities.products:
                matches[product.product_id] = self._merge_recommendation_product(
                    matches.get(product.product_id),
                    product,
                    candidate,
                )
        state.task_context.search_filters = state.task_context.search_filters.model_copy(
            deep=True,
            update={"ingredient_ids": ingredient_ids},
        )
        return sorted(
            matches.values(),
            key=lambda match: (
                0 if match.basis() is RecommendationBasis.EVIDENCE_SUPPORTED else 1
            ),
        )

    def _merge_recommendation_product(
        self,
        existing: RecommendationProductMatch | None,
        product: ProductRecord,
        candidate: IngredientRecommendationCandidate,
    ) -> RecommendationProductMatch:
        supported_ids = (
            [candidate.ingredient_id]
            if candidate.basis is RecommendationBasis.EVIDENCE_SUPPORTED
            else []
        )
        claim_only_ids = (
            [candidate.ingredient_id]
            if candidate.basis is RecommendationBasis.CLAIM_ONLY
            else []
        )
        if existing is None:
            return RecommendationProductMatch(
                product=product,
                evidence_supported_ingredient_ids=supported_ids,
                claim_only_ingredient_ids=claim_only_ids,
                statement_ids=candidate.statement_ids,
                evidence_ids=candidate.evidence_ids,
            )
        return existing.model_copy(
            deep=True,
            update={
                "evidence_supported_ingredient_ids": list(
                    dict.fromkeys(existing.evidence_supported_ingredient_ids + supported_ids)
                ),
                "claim_only_ingredient_ids": list(
                    dict.fromkeys(existing.claim_only_ingredient_ids + claim_only_ids)
                ),
                "statement_ids": list(
                    dict.fromkeys(existing.statement_ids + candidate.statement_ids)
                ),
                "evidence_ids": list(
                    dict.fromkeys(existing.evidence_ids + candidate.evidence_ids)
                ),
            },
        )

    def _recommendation_product_candidates(
        self,
        state: AgentState,
        matches: list[RecommendationProductMatch],
    ) -> list[ProductCandidate]:
        candidates: list[ProductCandidate] = []
        for rank, match in enumerate(matches, start=1):
            reasons = self._candidate_reasons(state.task_context.search_filters)
            reasons.extend(
                f"공인 Evidence가 확인된 성분 포함: {ingredient_id}"
                for ingredient_id in match.evidence_supported_ingredient_ids
            )
            reasons.extend(
                f"유사 사용자 사례에서 발굴된 탐색 성분 포함: {ingredient_id}"
                for ingredient_id in match.claim_only_ingredient_ids
            )
            limitations = self._product_limitations(match.product)
            if match.evidence_supported_ingredient_ids:
                limitations.append(EVIDENCE_PRODUCT_LIMITATION)
            if match.claim_only_ingredient_ids:
                limitations.append(CLAIM_ONLY_PRODUCT_LIMITATION)
            candidates.append(
                ProductCandidate(
                    rank=rank,
                    product=match.product,
                    reasons=list(dict.fromkeys(reasons)),
                    unresolved=list(dict.fromkeys(limitations)),
                )
            )
        return candidates

    def _append_recommendation_product_message(
        self,
        state: AgentState,
        candidates: list[ProductCandidate],
        matches: list[RecommendationProductMatch],
    ) -> None:
        supported_lines = [
            f"{candidate.rank}번. {candidate.product.name}"
            for candidate, match in zip(candidates, matches, strict=True)
            if match.basis() is RecommendationBasis.EVIDENCE_SUPPORTED
        ]
        claim_only_lines = [
            f"{candidate.rank}번. {candidate.product.name}"
            for candidate, match in zip(candidates, matches, strict=True)
            if match.basis() is RecommendationBasis.CLAIM_ONLY
        ]
        if supported_lines:
            state.response_parts.append(
                "공인 근거가 확인된 성분 기반 제품 후보:\n" + "\n".join(supported_lines)
            )
        if claim_only_lines:
            state.response_parts.append(
                "유사 사용자 사례에서 발굴된 탐색 제품 후보:\n"
                + "\n".join(claim_only_lines)
            )

    def _product_limitations(self, product: ProductRecord) -> list[str]:
        return (
            ["개발용 상품 데이터이며 실제 제품 검증 결과가 아님"] if product.is_demo else []
        ) + (["제품 사용법 미상"] if product.directions is None else []) + (
            ["제품 버전 미상"] if product.version is None else []
        )

    async def _search_products(
        self,
        state: AgentState,
        ingredient_ids: list[str],
        node: GraphNode,
    ) -> ResolvedEntities:
        parsed = self._require_parsed(state)
        if not self._reserve_tool_call(state, node):
            return ResolvedEntities(ingredient_ids=ingredient_ids)
        effective_category = parsed.category
        if effective_category is None and parsed.referenced_candidate_number is not None:
            referenced = self._candidate_by_rank(state, parsed.referenced_candidate_number)
            effective_category = referenced.product.category if referenced else None
        reference_filters = self._product_filters.normalize(
            ProductSearchFilters(
                category=effective_category,
                texture=parsed.texture,
                skin_feel=parsed.skin_feel,
            )
        )
        if reference_filters.unsupported_conditions:
            # 저장된 예전 분류도 현재 지원 목록에서 폐기됐을 수 있어 다시 검증한다.
            parsed.unsupported_product_conditions.extend(reference_filters.unsupported_conditions)
            return ResolvedEntities(ingredient_ids=ingredient_ids)

        effective_ingredient_ids = list(ingredient_ids)
        if Intent.PRODUCT_DISCOVERY in parsed.intents:
            previous_ids = state.task_context.search_filters.ingredient_ids
            if not effective_ingredient_ids and (parsed.is_modification or parsed.pending_answer):
                effective_ingredient_ids = list(previous_ids)
            state.task_context.search_filters = ProductSearchFilters(
                category=reference_filters.filters.category,
                texture=parsed.texture,
                skin_feel=parsed.skin_feel,
                ingredient_ids=effective_ingredient_ids,
            )
        filters = ProductSearchFilters(
            category=reference_filters.filters.category,
            texture=parsed.texture,
            skin_feel=parsed.skin_feel,
            ingredient_ids=effective_ingredient_ids,
        )
        result = await self._product_repository.search(
            ProductSearchRequest(
                query=parsed.query,
                allow_discovery=Intent.PRODUCT_DISCOVERY in parsed.intents,
                filters=filters,
            )
        )
        if result.status is LookupStatus.ERROR:
            self._add_tool_failure(state, result.error_message)
            return ResolvedEntities(ingredient_ids=effective_ingredient_ids)
        if result.status is LookupStatus.UNSUPPORTED:
            state.status = ChatStatus.PARTIAL
            details = result.unsupported_conditions or [
                result.error_message or "현재 상품 조회기가 이 조건을 지원하지 않습니다."
            ]
            state.unresolved.extend(
                UnresolvedItem(kind=UnresolvedKind.UNSUPPORTED_CONDITION, detail=detail)
                for detail in details
            )
            return ResolvedEntities(ingredient_ids=effective_ingredient_ids)
        products = result.products if result.status is LookupStatus.SUCCESS else []
        if Intent.PRODUCT_DISCOVERY in parsed.intents:
            products = [
                product
                for product in products
                if self._product_filters.matches(product, state.task_context.search_filters)
            ]
        return ResolvedEntities(
            products=products,
            ingredient_ids=effective_ingredient_ids,
        )

    async def _process_routine(self, state: AgentState) -> None:
        parsed = self._require_parsed(state)
        products = await self._routine_products(state)
        if not products:
            state.status = ChatStatus.PARTIAL
            state.unresolved.append(
                UnresolvedItem(
                    kind=UnresolvedKind.MISSING_INFORMATION,
                    detail="루틴에 배치할 제품을 복구할 수 없습니다.",
                )
            )
            state.response_parts.append("루틴에 배치할 제품을 확인하지 못했습니다.")
            return
        if not self._reserve_tool_call(state, GraphNode.PROCESS_TASK):
            return

        excluded_weekdays = self._merged_excluded_weekdays(state, parsed.excluded_weekdays)
        plan = await self._routine_planner.plan(
            RoutinePlanRequest(
                chat_room_id=state.chat_room_id,
                request_id=self._require_turn(state).request_id,
                products=products,
                user_request=parsed.query,
                excluded_weekdays=excluded_weekdays,
                evidence_records=state.evidence,
                current_plan=state.routine,
            )
        )
        if not self._reserve_tool_call(state, GraphNode.PROCESS_TASK):
            return
        validation = await self._routine_planner.validate(
            RoutineValidationRequest(
                plan=plan,
                products=products,
                excluded_weekdays=excluded_weekdays,
            )
        )
        if not validation.valid:
            state.status = ChatStatus.PARTIAL
            state.unresolved.extend(
                UnresolvedItem(kind=UnresolvedKind.CONFLICT, detail=violation)
                for violation in validation.violations
            )
            state.response_parts.append("루틴 제약 충돌로 계획을 확정하지 못했습니다.")
            return

        state.unresolved.extend(
            UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=warning)
            for warning in validation.warnings
        )
        if validation.warnings:
            # 출처가 불확실한 Rule을 일정에 강제하지 않았음을 최종 상태에서도 드러낸다.
            state.status = ChatStatus.PARTIAL

        state.routine = plan
        state.artifacts.append(plan)
        schedule = [
            f"{placement.weekday.value} {placement.period.value}: {placement.product_name}"
            for placement in plan.placements
        ]
        title = "개발용 루틴 초안:" if plan.is_demo else "루틴 초안:"
        state.response_parts.append(title + "\n" + "\n".join(schedule))
        if any(product.is_demo and "retinol" in product.product_id for product in products):
            state.unresolved.append(
                UnresolvedItem(
                    kind=UnresolvedKind.MISSING_INFORMATION,
                    detail="레티놀 fixture의 실제 사용 빈도와 내약성은 검증되지 않았습니다.",
                )
            )

    async def _routine_products(self, state: AgentState) -> list[ProductRecord]:
        parsed = self._require_parsed(state)
        rejected_ids = set(state.task_context.rejected_product_ids)
        rejected_ids.update(
            candidate.product.product_id
            for rank in parsed.rejected_candidate_numbers
            if (candidate := self._candidate_by_rank(state, rank)) is not None
        )
        state.task_context.rejected_product_ids = sorted(rejected_ids)
        if parsed.referenced_candidate_number is not None and (
            parsed.referenced_candidate_number not in parsed.rejected_candidate_numbers
        ):
            candidate = self._candidate_by_rank(state, parsed.referenced_candidate_number)
            return (
                [candidate.product]
                if candidate and candidate.product.product_id not in rejected_ids
                else []
            )
        if state.resolved_entities.products:
            return [
                product
                for product in state.resolved_entities.products
                if product.product_id not in rejected_ids
            ]
        if state.routine is None:
            return []

        products: list[ProductRecord] = []
        product_ids = list(
            dict.fromkeys(placement.product_id for placement in state.routine.placements)
        )
        for product_id in product_ids:
            if product_id in rejected_ids:
                continue
            if not self._reserve_tool_call(state, GraphNode.PROCESS_TASK):
                return products
            result = await self._product_repository.get(ProductGetRequest(product_id=product_id))
            if result.status is LookupStatus.ERROR:
                self._add_tool_failure(state, result.error_message)
                return []
            if result.product is None:
                return []
            products.append(result.product)
        return products

    def _merged_excluded_weekdays(
        self,
        state: AgentState,
        current_exclusions: list[Weekday],
    ) -> list[Weekday]:
        return list(dict.fromkeys(state.task_context.excluded_weekdays + current_exclusions))

    def _execution_limit_reached(self, state: AgentState) -> bool:
        return self._runtime.execution_limit_reached(state, GraphNode.PROCESS_TASK)

    def _reserve_tool_call(self, state: AgentState, node: GraphNode) -> bool:
        return self._runtime.reserve_tool_call(state, node)

    def _add_tool_failure(self, state: AgentState, detail: str | None) -> None:
        self._runtime.add_tool_failure(state, detail)

    def _candidate_by_rank(
        self,
        state: AgentState,
        rank: int,
    ) -> ProductCandidate | None:
        if state.candidate_set is None:
            return None
        return next(
            (candidate for candidate in state.candidate_set.candidates if candidate.rank == rank),
            None,
        )

    def _candidate_reasons(
        self,
        filters: ProductSearchFilters,
    ) -> list[str]:
        reasons = ["현재 상품 조회 결과에서 선택"]
        if filters.category is not None:
            reasons.append("요청한 제품 카테고리와 일치")
        if filters.texture is not None:
            reasons.append("요청한 제형 조건과 일치")
        if filters.skin_feel is not None:
            reasons.append("요청한 사용감 조건과 일치")
        return reasons

    def _ingredient_request(self, query: str) -> IngredientResolveRequest:
        return IngredientResolveRequest(name=query)

    def _stable_id(self, state: AgentState, namespace: str) -> str:
        return self._runtime.stable_id(state, namespace)

    def _next_sequence(self, state: AgentState) -> int:
        return max((message.sequence for message in state.messages), default=0) + 1

    def _record_event(self, state: AgentState, node: GraphNode, detail: str) -> None:
        self._runtime.record_node(state, node, detail)

    def _require_turn(self, state: AgentState) -> ChatTurnInput:
        return self._runtime.require_turn(state)

    def _require_parsed(self, state: AgentState) -> ParsedRequest:
        return self._runtime.require_parsed(state)

    def _require_turn_fields(self, state: AgentState) -> None:
        if not state.chat_room_id or not state.thread_id:
            raise RuntimeError("그래프 상태에 채팅방 또는 thread 식별자가 없습니다.")
