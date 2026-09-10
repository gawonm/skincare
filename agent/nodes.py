"""LangGraph 각 단계의 상태 전이를 구현한다."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from agent.context import ContextBuilder
from agent.ports import IngredientRepository, LlmClient, ProductRepository, RoutinePlanner
from agent.prompts import PromptCatalog, PromptPurpose, PromptRequest
from agent.rag.pipeline import EvidencePipeline
from agent.rag.retrieval.product_filter_validator import ProductFilterValidator
from agent.rag.schemas import (
    ApplicabilityStatus,
    EvidenceBundle,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceSearchRequest,
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
    UnverifiableReason,
    Weekday,
)
from agent.schemas import (
    AgentState,
    ChatMessage,
    ChatStatus,
    ChatTurnInput,
    ChatTurnOutput,
    Citation,
    ErrorCode,
    EvidenceAnswer,
    ExecutionEvent,
    ExecutionEventKind,
    GraphNode,
    Intent,
    MessageRole,
    ParsedRequest,
    PendingQuestion,
    ResolvedEntities,
    RoutineSaveHandoff,
    SessionSnapshot,
    SourcedValue,
    UnderstandingRequest,
    UnresolvedItem,
    UnresolvedKind,
    ValueOrigin,
)

DEMO_RESULT_NOTICE = "개발용 fixture 결과이며 실제 제품·임상 검증 결과가 아닙니다."
PRODUCT_TARGET_QUESTION = "루틴에 사용할 제품명을 알려주세요."
EVIDENCE_TARGET_QUESTION = "설명할 성분이나 비교할 두 제품을 구체적으로 알려주세요."
CANDIDATE_REFERENCE_QUESTION = (
    "참조한 후보 번호를 현재 목록에서 찾을 수 없습니다. 번호를 다시 알려주세요."
)
ROUTINE_REFERENCE_QUESTION = "참조한 루틴 버전을 현재 방에서 찾을 수 없습니다. 다시 선택해 주세요."
NO_RESULT_MESSAGE = "현재 상품 데이터에서 조건을 만족하는 제품을 찾지 못했습니다."
NO_EVIDENCE_MESSAGE = "현재 연결된 검색 자료에서 관련 근거를 찾지 못했습니다."


class AgentNodes:
    """주입된 포트만 사용해 그래프 노드를 실행한다."""

    _EVIDENCE_REFERENCES = ("이 성분", "그 성분", "해당 성분", "이 제품", "그 제품")

    def __init__(
        self,
        llm: LlmClient,
        product_repository: ProductRepository,
        ingredient_repository: IngredientRepository,
        evidence_pipeline: EvidencePipeline,
        routine_planner: RoutinePlanner,
        context_builder: ContextBuilder,
        prompt_catalog: PromptCatalog,
        product_taxonomy: ProductTaxonomy,
    ) -> None:
        self._llm = llm
        self._product_repository = product_repository
        self._ingredient_repository = ingredient_repository
        self._evidence_pipeline = evidence_pipeline
        self._routine_planner = routine_planner
        self._context_builder = context_builder
        self._prompt_catalog = prompt_catalog
        self._product_taxonomy = product_taxonomy.model_copy(deep=True)
        self._product_filters = ProductFilterValidator(self._product_taxonomy)

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
        state.task_queue = list(state.parsed_request.intents)
        self._record_event(state, GraphNode.UNDERSTAND_REQUEST, "목적과 조건을 추출했습니다.")
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
        for mention in parsed.ingredient_mentions or [parsed.query]:
            if not self._reserve_tool_call(state, GraphNode.RESOLVE_ENTITIES):
                break
            ingredient_result = await self._ingredient_repository.resolve(
                self._ingredient_request(mention)
            )
            if ingredient_result.status is LookupStatus.ERROR:
                self._add_tool_failure(state, ingredient_result.error_message)
            elif ingredient_result.ambiguous_candidates:
                unresolved_names.append(mention)
            elif ingredient_result.ingredient:
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
        if (
            needs_products
            and not parsed.unsupported_product_conditions
            and self._reserve_tool_call(state, GraphNode.RESOLVE_ENTITIES)
        ):
            effective_category = parsed.category
            if effective_category is None and parsed.referenced_candidate_number is not None:
                referenced = self._candidate_by_rank(
                    state,
                    parsed.referenced_candidate_number,
                )
                effective_category = referenced.product.category if referenced else None
            reference_filters = self._product_filters.normalize(
                ProductSearchFilters(
                    category=effective_category, texture=parsed.texture, skin_feel=parsed.skin_feel
                )
            )
            if reference_filters.unsupported_conditions:
                # 이전 후보에서 가져온 분류도 현재 목록에서 폐기되었을 수 있다.
                parsed.unsupported_product_conditions.extend(
                    reference_filters.unsupported_conditions
                )
                state.resolved_entities = ResolvedEntities(
                    ingredient_ids=list(dict.fromkeys(ingredient_ids)),
                    unresolved_names=unresolved_names,
                )
                return state
            effective_category = reference_filters.filters.category
            if Intent.PRODUCT_DISCOVERY in parsed.intents:
                previous_ids = state.task_context.search_filters.ingredient_ids
                if not ingredient_ids and (parsed.is_modification or parsed.pending_answer):
                    ingredient_ids = list(previous_ids)
                state.task_context.search_filters = ProductSearchFilters(
                    category=effective_category,
                    texture=parsed.texture,
                    skin_feel=parsed.skin_feel,
                    ingredient_ids=ingredient_ids,
                )
            product_result = await self._product_repository.search(
                ProductSearchRequest(
                    query=parsed.query,
                    allow_discovery=Intent.PRODUCT_DISCOVERY in parsed.intents,
                    filters=ProductSearchFilters(
                        category=effective_category,
                        texture=parsed.texture,
                        skin_feel=parsed.skin_feel,
                        ingredient_ids=ingredient_ids,
                    ),
                )
            )
            if product_result.status is LookupStatus.ERROR:
                self._add_tool_failure(state, product_result.error_message)
            elif product_result.status is LookupStatus.UNSUPPORTED:
                state.status = ChatStatus.PARTIAL
                state.unresolved.extend(
                    UnresolvedItem(
                        kind=UnresolvedKind.UNSUPPORTED_CONDITION,
                        detail=condition,
                    )
                    for condition in product_result.unsupported_conditions
                    or [
                        product_result.error_message
                        or "현재 상품 조회기가 이 조건을 지원하지 않습니다."
                    ]
                )
            # 실패·미지원 응답의 후보를 성공 결과로 섞지 않는다.
            products = (
                product_result.products if product_result.status is LookupStatus.SUCCESS else []
            )
            if Intent.PRODUCT_DISCOVERY in parsed.intents:
                products = [
                    product
                    for product in products
                    if self._product_filters.matches(product, state.task_context.search_filters)
                ]

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
        elif state.resolved_entities.unresolved_names:
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
            if not has_products and not has_reference and not has_current_routine:
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
        elif intent is Intent.EVIDENCE_QA:
            await self._process_evidence(state)
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
        products = [
            product
            for product in state.resolved_entities.products
            if product.product_id not in state.task_context.rejected_product_ids
        ]
        if not products:
            state.status = ChatStatus.PARTIAL
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=NO_RESULT_MESSAGE)
            )
            state.response_parts.append(NO_RESULT_MESSAGE)
            return

        candidates = [
            ProductCandidate(
                rank=rank,
                product=product,
                reasons=self._candidate_reasons(state.task_context.search_filters),
                unresolved=(
                    ["개발용 상품 데이터이며 실제 제품 검증 결과가 아님"] if product.is_demo else []
                )
                + (["제품 사용법 미상"] if product.directions is None else [])
                + (["제품 버전 미상"] if product.version is None else []),
            )
            for rank, product in enumerate(products, start=1)
        ]
        candidate_set = ProductCandidateSet(
            candidate_set_id=self._stable_id(state, "candidates"),
            candidates=candidates,
            is_demo=any(product.is_demo for product in products),
        )
        state.candidate_set = candidate_set
        state.artifacts.append(candidate_set)
        lines = [f"{candidate.rank}번. {candidate.product.name}" for candidate in candidates]
        title = "개발용 제품 후보:" if candidate_set.is_demo else "조건에 맞는 제품 후보:"
        state.response_parts.append(title + "\n" + "\n".join(lines))

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
                excluded_weekdays=excluded_weekdays,
                current_plan=state.routine,
            )
        )
        if not self._reserve_tool_call(state, GraphNode.PROCESS_TASK):
            return
        validation = await self._routine_planner.validate(
            RoutineValidationRequest(plan=plan, excluded_weekdays=excluded_weekdays)
        )
        if not validation.valid:
            state.status = ChatStatus.PARTIAL
            state.unresolved.extend(
                UnresolvedItem(kind=UnresolvedKind.CONFLICT, detail=violation)
                for violation in validation.violations
            )
            state.response_parts.append("루틴 제약 충돌로 계획을 확정하지 못했습니다.")
            return

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

    async def _process_evidence(self, state: AgentState) -> None:
        parsed = self._require_parsed(state)
        if not self._reserve_tool_call(state, GraphNode.PROCESS_TASK):
            return
        products = list(state.resolved_entities.products)
        if parsed.referenced_candidate_number is not None:
            candidate = self._candidate_by_rank(state, parsed.referenced_candidate_number)
            if candidate:
                products.append(candidate.product)
        target_ids = list(
            dict.fromkeys(
                state.resolved_entities.ingredient_ids
                + [product.product_id for product in products]
                + [ingredient for product in products for ingredient in product.ingredient_ids]
            )
        )
        combination_target_ids = (
            [product.product_id for product in products]
            if products
            else list(state.resolved_entities.ingredient_ids)
        )
        known_conditions = parsed.known_conditions
        if (
            not target_ids
            and not parsed.ingredient_mentions
            and any(word in parsed.query for word in self._EVIDENCE_REFERENCES)
        ):
            target_ids = list(state.task_context.evidence_target_ids)
            combination_target_ids = list(state.task_context.evidence_combination_target_ids)
            known_conditions = state.task_context.evidence_conditions.model_copy(deep=True)
            for field in EvidenceConditions.model_fields:
                value = getattr(parsed.known_conditions, field)
                if value is not None:
                    setattr(known_conditions, field, value)
        # 자료가 없더라도 최근에 명확히 식별한 대상을 유지해야 이전 주제로 되돌아가지 않는다.
        state.task_context.evidence_target_ids = target_ids
        state.task_context.evidence_combination_target_ids = combination_target_ids
        state.task_context.evidence_conditions = known_conditions.model_copy(deep=True)
        bundle = await self._evidence_pipeline.run(
            EvidenceSearchRequest(
                query=parsed.query,
                target_ids=target_ids,
                known_conditions=known_conditions,
                combination_target_ids=combination_target_ids,
            )
        )
        if bundle.search.status is LookupStatus.ERROR:
            self._add_tool_failure(state, bundle.search.error_message)
            state.response_parts.append("근거 검색 도구가 실패해 확인 가능한 범위만 반환합니다.")
            return
        if bundle.search.status is LookupStatus.NO_RESULTS:
            state.status = ChatStatus.PARTIAL
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.NO_EVIDENCE, detail=NO_EVIDENCE_MESSAGE)
            )
            state.response_parts.append(NO_EVIDENCE_MESSAGE)
            return

        if bundle.search.status is LookupStatus.UNSUPPORTED:
            state.status = ChatStatus.PARTIAL
            detail = (
                bundle.search.error_message or "현재 검색기가 이 근거 요청을 지원하지 않습니다."
            )
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.UNSUPPORTED_CONDITION, detail=detail)
            )
            state.response_parts.append(detail)
            return
        if bundle.generated is not None:
            self._append_generated_evidence(state, bundle)
            return
        excluded_ids = {
            item.evidence_id
            for item in bundle.assessments
            if item.status is ApplicabilityStatus.NOT_APPLICABLE
        }
        records = [
            record for record in bundle.search.records if record.evidence_id not in excluded_ids
        ]
        if not records:
            state.status = ChatStatus.PARTIAL
            state.response_parts.append("검색된 근거를 현재 조건에 적용할 수 없습니다.")
            state.unresolved.extend(
                UnresolvedItem(kind=UnresolvedKind.UNSUPPORTED_CONDITION, detail=reason)
                for item in bundle.assessments
                for reason in item.reasons
            )
            return
        known_ids = {record.evidence_id for record in state.evidence}
        state.evidence.extend(record for record in records if record.evidence_id not in known_ids)
        state.citations.extend(self._citation(record) for record in records)
        answer = EvidenceAnswer(
            answer_id=self._stable_id(state, "evidence-answer"),
            subject=parsed.query,
            summary="\n".join(f"[{record.source_title}] {record.text}" for record in records),
            evidence_ids=[record.evidence_id for record in records],
            assessments=bundle.assessments,
            is_demo=any(record.is_demo for record in records),
        )
        state.artifacts.append(answer)
        state.response_parts.append(answer.summary)
        limitations = list(
            dict.fromkeys(
                reason
                for item in bundle.assessments
                for reason in item.reasons
                if item.status is not ApplicabilityStatus.APPLICABLE
            )
        )
        if limitations:
            state.response_parts.append("적용 한계: " + "; ".join(limitations))
        if any(word in parsed.query for word in ("병용", "같이", "괜찮")):
            state.response_parts.append(
                "개별 성분 자료만으로 두 완제품의 병용 안전성을 확정할 수 없습니다."
            )
        if "농도" in parsed.query or "ph" in parsed.query.casefold():
            state.unresolved.append(
                UnresolvedItem(
                    kind=UnresolvedKind.MISSING_INFORMATION,
                    detail="개발 fixture에는 제품별 공개 농도 또는 pH가 없습니다.",
                )
            )
        for assessment in bundle.assessments:
            if assessment.status is not ApplicabilityStatus.APPLICABLE:
                state.unresolved.extend(
                    UnresolvedItem(
                        kind=UnresolvedKind.MISSING_INFORMATION,
                        detail=f"{assessment.evidence_id}: {reason}",
                    )
                    for reason in assessment.reasons
                )

    def _append_generated_evidence(self, state: AgentState, bundle: EvidenceBundle) -> None:
        generated = bundle.generated
        if generated is None:
            raise ValueError("생성된 RAG 결과가 없습니다.")
        results = [
            (f"대상 {index}", item.result)
            for index, item in enumerate(generated.per_target, start=1)
        ]
        if generated.combination is not None:
            results.append(("병용 근거", generated.combination))
        if generated.free_text is not None:
            results.append(("질문에 대한 근거", generated.free_text))
        messages: list[str] = []
        records: dict[str, EvidenceRecord] = {}
        for label, result in results:
            if result.has_verifiable_evidence:
                messages.append(f"{label}: {result.answer}")
                for claim in result.claims:
                    for record in claim.sources:
                        records[record.evidence_id] = record
            else:
                reason = result.unverifiable_reason or UnverifiableReason.NO_EVIDENCE_FOUND
                detail = self._unverifiable_message(reason)
                messages.append(f"{label}: {detail}")
                state.status = ChatStatus.PARTIAL
                state.unresolved.append(
                    UnresolvedItem(kind=UnresolvedKind.NO_EVIDENCE, detail=detail)
                )
        for item in bundle.assessments:
            if item.evidence_id in records and item.status is not ApplicabilityStatus.APPLICABLE:
                messages.append("적용 한계: " + "; ".join(item.reasons))
        summary = "\n".join(messages) or NO_EVIDENCE_MESSAGE
        state.evidence.extend(records.values())
        state.citations.extend(self._citation(record) for record in records.values())
        state.artifacts.append(
            EvidenceAnswer(
                answer_id=self._stable_id(state, "evidence-answer"),
                subject=self._require_parsed(state).query,
                summary=summary,
                evidence_ids=list(records),
                assessments=bundle.assessments,
                is_demo=any(record.is_demo for record in records.values()),
                generated=generated,
            )
        )
        state.response_parts.append(summary)

    def _unverifiable_message(self, reason: UnverifiableReason) -> str:
        messages = {
            UnverifiableReason.NO_EVIDENCE_FOUND: "확인할 근거를 찾지 못했습니다.",
            UnverifiableReason.UNREVIEWED_EVIDENCE: "검수된 근거가 없어 답변을 보류합니다.",
            UnverifiableReason.NOT_RELEVANT_TO_QUESTION: "질문이 묻는 항목을 뒷받침할 근거가 부족합니다.",
            UnverifiableReason.MISSING_COMBINATION_EVIDENCE: "질문의 대상들을 함께 다루는 병용 근거가 없습니다.",
            UnverifiableReason.CITATION_VALIDATION_FAILED: "출처 또는 적용 조건 검증을 통과한 답변이 없습니다.",
        }
        return messages[reason]

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
        elapsed = (datetime.now(UTC) - state.started_at).total_seconds()
        if state.tool_call_count >= state.execution_limits.max_tool_calls:
            self._mark_limit(state, "최대 도구 호출 수에 도달했습니다.")
            return True
        if elapsed >= state.execution_limits.timeout_seconds:
            self._mark_limit(state, "요청 실행 시간 제한에 도달했습니다.")
            return True
        return False

    def _reserve_tool_call(self, state: AgentState, node: GraphNode) -> bool:
        if self._execution_limit_reached(state):
            return False
        state.tool_call_count += 1
        state.events.append(
            ExecutionEvent(
                node=node,
                kind=ExecutionEventKind.TOOL_CALLED,
                detail=f"도구 호출 {state.tool_call_count}회",
            )
        )
        return True

    def _mark_limit(self, state: AgentState, detail: str) -> None:
        if state.error_code is ErrorCode.EXECUTION_LIMIT_REACHED:
            return
        state.status = ChatStatus.PARTIAL
        state.error_code = ErrorCode.EXECUTION_LIMIT_REACHED
        state.retryable = True
        state.response_parts.append(detail)
        state.unresolved.append(
            UnresolvedItem(
                kind=UnresolvedKind.CONFLICT,
                detail=detail,
                retryable=True,
            )
        )
        state.events.append(
            ExecutionEvent(
                node=GraphNode.PROCESS_TASK,
                kind=ExecutionEventKind.LIMIT_REACHED,
                detail=detail,
            )
        )

    def _add_tool_failure(self, state: AgentState, detail: str | None) -> None:
        message = detail or "도구가 원인을 제공하지 않고 실패했습니다."
        state.status = ChatStatus.PARTIAL
        state.error_code = ErrorCode.TOOL_FAILED
        state.retryable = True
        state.unresolved.append(
            UnresolvedItem(
                kind=UnresolvedKind.TOOL_FAILURE,
                detail=message,
                retryable=True,
            )
        )

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

    def _citation(self, record: EvidenceRecord) -> Citation:
        return Citation(
            source_type=record.source_type,
            text_kind=record.text_kind,
            scope=record.scope,
            jurisdiction=record.jurisdiction,
            evidence_id=record.evidence_id,
            source_id=record.source_id,
            locator=record.locator,
            source_title=record.source_title,
            document_version=record.document_version,
            url=record.url,
            is_demo=record.is_demo,
        )

    def _ingredient_request(self, query: str) -> IngredientResolveRequest:
        return IngredientResolveRequest(name=query)

    def _stable_id(self, state: AgentState, namespace: str) -> str:
        turn = self._require_turn(state)
        return str(uuid5(NAMESPACE_URL, f"{namespace}:{state.chat_room_id}:{turn.request_id}"))

    def _next_sequence(self, state: AgentState) -> int:
        return max((message.sequence for message in state.messages), default=0) + 1

    def _record_event(self, state: AgentState, node: GraphNode, detail: str) -> None:
        state.events.append(
            ExecutionEvent(node=node, kind=ExecutionEventKind.NODE_COMPLETED, detail=detail)
        )

    def _require_turn(self, state: AgentState) -> ChatTurnInput:
        if state.turn_input is None:
            raise RuntimeError("그래프 상태에 현재 사용자 입력이 없습니다.")
        return state.turn_input

    def _require_parsed(self, state: AgentState) -> ParsedRequest:
        if state.parsed_request is None:
            raise RuntimeError("요청 해석 결과 없이 다음 노드를 실행할 수 없습니다.")
        return state.parsed_request

    def _require_turn_fields(self, state: AgentState) -> None:
        if not state.chat_room_id or not state.thread_id:
            raise RuntimeError("그래프 상태에 채팅방 또는 thread 식별자가 없습니다.")
