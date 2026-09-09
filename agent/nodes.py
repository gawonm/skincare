"""LangGraph 각 단계의 상태 전이를 구현한다."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from agent.context import ContextBuilder
from agent.ports import IngredientRepository, LlmClient, ProductRepository, RoutinePlanner
from agent.prompts import PromptCatalog, PromptPurpose, PromptRequest
from agent.rag.pipeline import EvidencePipeline
from agent.rag.schemas import (
    ApplicabilityStatus,
    ConstraintSource,
    EvidenceRecord,
    EvidenceSearchRequest,
    IngredientResolveRequest,
    LookupStatus,
    ProductCandidate,
    ProductCandidateSet,
    ProductCategory,
    ProductGetRequest,
    ProductRecord,
    ProductSearchFilters,
    ProductSearchRequest,
    ProductTexture,
    RoutinePlanRequest,
    RoutineValidationRequest,
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
NO_RESULT_MESSAGE = "조건을 만족하는 개발용 제품 fixture를 찾지 못했습니다."
NO_EVIDENCE_MESSAGE = "현재 개발용 근거 fixture에서 관련 자료를 찾지 못했습니다."


class AgentNodes:
    """주입된 포트만 사용해 그래프 노드를 실행한다."""

    def __init__(
        self,
        llm: LlmClient,
        product_repository: ProductRepository,
        ingredient_repository: IngredientRepository,
        evidence_pipeline: EvidencePipeline,
        routine_planner: RoutinePlanner,
        context_builder: ContextBuilder,
        prompt_catalog: PromptCatalog,
    ) -> None:
        self._llm = llm
        self._product_repository = product_repository
        self._ingredient_repository = ingredient_repository
        self._evidence_pipeline = evidence_pipeline
        self._routine_planner = routine_planner
        self._context_builder = context_builder
        self._prompt_catalog = prompt_catalog

    async def prepare_turn(self, state: AgentState) -> AgentState:
        self._require_turn_fields(state)
        snapshot = state.restored_snapshot
        if snapshot is not None:
            # 히스토리의 완료 스냅샷을 기준으로 삼아 실패한 실행의 체크포인트가
            # 다음 요청 상태를 앞질러 가지 못하게 한다.
            state.messages = [message.model_copy(deep=True) for message in snapshot.messages]
            state.profile = snapshot.profile.model_copy(deep=True)
            state.pending_question = (
                snapshot.pending_question.model_copy(deep=True)
                if snapshot.pending_question
                else None
            )
            state.candidate_set = (
                snapshot.candidate_set.model_copy(deep=True) if snapshot.candidate_set else None
            )
            state.routine = snapshot.routine.model_copy(deep=True) if snapshot.routine else None
            state.evidence = [record.model_copy(deep=True) for record in snapshot.evidence]
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

        identifiers = state.identifiers
        turn = state.turn_input
        if identifiers is None or turn is None:
            raise RuntimeError("그래프 호출에 요청 식별자 또는 사용자 입력이 없습니다.")
        if not any(message.message_id == identifiers.user_message_id for message in state.messages):
            state.messages.append(
                ChatMessage(
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
            )
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

        if self._reserve_tool_call(state, GraphNode.RESOLVE_ENTITIES):
            ingredient_result = await self._ingredient_repository.resolve(
                self._ingredient_request(parsed.query)
            )
            if ingredient_result.ingredient:
                ingredient_ids.append(ingredient_result.ingredient.ingredient_id)
            ingredient_ids.extend(
                ingredient.ingredient_id for ingredient in ingredient_result.ambiguous_candidates
            )

        needs_products = any(
            intent in parsed.intents
            for intent in (Intent.PRODUCT_DISCOVERY, Intent.ROUTINE_PLANNING)
        )
        if needs_products and self._reserve_tool_call(state, GraphNode.RESOLVE_ENTITIES):
            effective_category = parsed.category
            if effective_category is None and parsed.referenced_candidate_number is not None:
                referenced = self._candidate_by_rank(
                    state,
                    parsed.referenced_candidate_number,
                )
                effective_category = referenced.product.category if referenced else None
            product_result = await self._product_repository.search(
                ProductSearchRequest(
                    query=parsed.query,
                    filters=ProductSearchFilters(
                        category=effective_category,
                        texture=parsed.texture,
                        ingredient_ids=ingredient_ids,
                    ),
                )
            )
            if product_result.status is LookupStatus.ERROR:
                self._add_tool_failure(state, product_result.error_message)
            elif product_result.status is LookupStatus.UNSUPPORTED:
                state.unresolved.extend(
                    UnresolvedItem(
                        kind=UnresolvedKind.UNSUPPORTED_CONDITION,
                        detail=condition,
                    )
                    for condition in product_result.unsupported_conditions
                )
            products = product_result.products

        state.resolved_entities = ResolvedEntities(
            products=products,
            ingredient_ids=list(dict.fromkeys(ingredient_ids)),
        )
        self._record_event(state, GraphNode.RESOLVE_ENTITIES, "성분과 제품 식별을 마쳤습니다.")
        return state

    async def assess_information(self, state: AgentState) -> AgentState:
        parsed = self._require_parsed(state)
        question: str | None = None
        target_field: str | None = None
        reason: str | None = None
        turn = self._require_turn(state)

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
            has_reference = parsed.referenced_candidate_number is not None
            has_current_routine = state.routine is not None
            if not has_products and not has_reference and not has_current_routine:
                question = PRODUCT_TARGET_QUESTION
                target_field = "routine_products"
                reason = "제품이 식별되지 않으면 제품별 사용 계획을 만들 수 없습니다."

        demonstrative_query = "이 성분" in parsed.query or "이 제품" in parsed.query
        if (
            question is None
            and Intent.EVIDENCE_QA in parsed.intents
            and demonstrative_query
            and not state.resolved_entities.ingredient_ids
            and not state.resolved_entities.products
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
        if state.artifacts and DEMO_RESULT_NOTICE not in parts:
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
        self._record_event(state, GraphNode.FINALIZE_RESPONSE, "구조화된 응답을 만들었습니다.")
        return state

    async def _process_product_discovery(self, state: AgentState) -> None:
        parsed = self._require_parsed(state)
        rejected_product_ids = {
            candidate.product.product_id
            for rank in parsed.rejected_candidate_numbers
            if (candidate := self._candidate_by_rank(state, rank)) is not None
        }
        products = [
            product
            for product in state.resolved_entities.products
            if product.product_id not in rejected_product_ids
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
                reasons=self._candidate_reasons(parsed.category, parsed.texture),
                unresolved=["실제 제품 데이터와 효능 근거는 아직 연결되지 않음"],
            )
            for rank, product in enumerate(products, start=1)
        ]
        candidate_set = ProductCandidateSet(
            candidate_set_id=self._stable_id(state, "candidates"),
            candidates=candidates,
            is_demo=True,
        )
        state.candidate_set = candidate_set
        state.artifacts.append(candidate_set)
        lines = [f"{candidate.rank}번. {candidate.product.name}" for candidate in candidates]
        state.response_parts.append("개발용 제품 후보:\n" + "\n".join(lines))

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
        state.response_parts.append("개발용 루틴 초안:\n" + "\n".join(schedule))
        if any("retinol" in product.product_id for product in products):
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
        bundle = await self._evidence_pipeline.run(
            EvidenceSearchRequest(
                query=parsed.query,
                target_ids=state.resolved_entities.ingredient_ids,
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

        records = bundle.search.records
        known_ids = {record.evidence_id for record in state.evidence}
        state.evidence.extend(record for record in records if record.evidence_id not in known_ids)
        state.citations.extend(self._citation(record) for record in records)
        answer = EvidenceAnswer(
            answer_id=self._stable_id(state, "evidence-answer"),
            subject=parsed.query,
            summary=" ".join(record.text for record in records),
            evidence_ids=[record.evidence_id for record in records],
            is_demo=True,
        )
        state.artifacts.append(answer)
        state.response_parts.append(answer.summary)
        if "농도" in parsed.query or "ph" in parsed.query.casefold():
            state.unresolved.append(
                UnresolvedItem(
                    kind=UnresolvedKind.MISSING_INFORMATION,
                    detail="개발 fixture에는 제품별 공개 농도 또는 pH가 없습니다.",
                )
            )
        for assessment in bundle.assessments:
            if assessment.status is ApplicabilityStatus.LIMITED:
                state.unresolved.extend(
                    UnresolvedItem(
                        kind=UnresolvedKind.MISSING_INFORMATION,
                        detail=f"{assessment.evidence_id}: {reason}",
                    )
                    for reason in assessment.reasons
                )

    async def _routine_products(self, state: AgentState) -> list[ProductRecord]:
        parsed = self._require_parsed(state)
        if parsed.referenced_candidate_number is not None:
            candidate = self._candidate_by_rank(state, parsed.referenced_candidate_number)
            return [candidate.product] if candidate else []
        if state.resolved_entities.products:
            return state.resolved_entities.products
        if state.routine is None:
            return []

        products: list[ProductRecord] = []
        product_ids = list(
            dict.fromkeys(placement.product_id for placement in state.routine.placements)
        )
        for product_id in product_ids:
            if not self._reserve_tool_call(state, GraphNode.PROCESS_TASK):
                return products
            result = await self._product_repository.get(ProductGetRequest(product_id=product_id))
            if result.product:
                products.append(result.product)
        return products

    def _merged_excluded_weekdays(
        self,
        state: AgentState,
        current_exclusions: list[Weekday],
    ) -> list[Weekday]:
        exclusions = list(current_exclusions)
        if state.routine:
            for constraint in state.routine.constraints:
                if constraint.source is not ConstraintSource.USER:
                    continue
                for weekday in Weekday:
                    if constraint.description.startswith(weekday.value):
                        exclusions.append(weekday)
        return list(dict.fromkeys(exclusions))

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
        category: ProductCategory | None,
        texture: ProductTexture | None,
    ) -> list[str]:
        reasons = ["개발용 제품 fixture의 구조화 조건과 일치"]
        if category is not None:
            reasons.append("요청한 제품 카테고리와 일치")
        if texture is not None:
            reasons.append("요청한 제형 조건과 일치")
        return reasons

    def _citation(self, record: EvidenceRecord) -> Citation:
        return Citation(
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
