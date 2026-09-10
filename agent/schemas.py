"""LangGraph 실행, 채팅 서비스, 히스토리 계약의 공용 타입."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agent.rag.schemas import (
    ApplicabilityAssessment,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceScope,
    EvidenceSourceType,
    EvidenceTextKind,
    ProductCandidateSet,
    ProductCategory,
    ProductRecord,
    ProductSearchFilters,
    ProductSkinFeel,
    ProductTaxonomy,
    ProductTexture,
    RagQueryResult,
    RoutinePlan,
    Weekday,
)

DEFAULT_CONTEXT_MESSAGE_LIMIT = 8
DEFAULT_SUMMARY_TRIGGER = 12
DEFAULT_MAX_TOOL_CALLS = 8
DEFAULT_MAX_REVISIONS = 2
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RECURSION_LIMIT = 40
DEFAULT_SUMMARY_CHAR_LIMIT = 2000
DEFAULT_MESSAGE_CHAR_LIMIT = 2000


class UtcClock:
    """테스트와 모델 기본값이 모두 시간대가 있는 UTC를 사용하게 한다."""

    @classmethod
    def now(cls) -> datetime:
        return datetime.now(UTC)


class AgentModel(BaseModel):
    """에이전트 경계에서 스키마 변경을 즉시 발견하기 위한 기본 모델."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Intent(StrEnum):
    PRODUCT_DISCOVERY = "product_discovery"
    ROUTINE_PLANNING = "routine_planning"
    EVIDENCE_QA = "evidence_qa"
    GENERAL_CHAT = "general_chat"
    OUT_OF_SCOPE = "out_of_scope"
    CLARIFICATION = "clarification"
    ROUTINE_SAVE = "routine_save"


class ChatStatus(StrEnum):
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    PARTIAL = "partial"
    ERROR = "error"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ValueOrigin(StrEnum):
    USER = "user"
    DATA = "data"
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"


class ErrorCode(StrEnum):
    ROOM_NOT_FOUND = "room_not_found"
    ROOM_FORBIDDEN = "room_forbidden"
    REQUEST_CONFLICT = "request_conflict"
    REQUEST_IN_PROGRESS = "request_in_progress"
    GRAPH_EXECUTION_FAILED = "graph_execution_failed"
    RESPONSE_SAVE_FAILED = "response_save_failed"
    EXECUTION_LIMIT_REACHED = "execution_limit_reached"
    TOOL_FAILED = "tool_failed"


class UnresolvedKind(StrEnum):
    MISSING_INFORMATION = "missing_information"
    UNSUPPORTED_CONDITION = "unsupported_condition"
    NO_EVIDENCE = "no_evidence"
    TOOL_FAILURE = "tool_failure"
    CONFLICT = "conflict"


class TurnBeginStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    STAGED = "staged"
    CONFLICT = "conflict"
    FAILED = "failed"


class TurnFailureCode(StrEnum):
    GRAPH = "graph"
    STORAGE = "storage"


class SummarySaveStatus(StrEnum):
    SAVED = "saved"
    REVISION_CONFLICT = "revision_conflict"
    NO_SNAPSHOT = "no_snapshot"


class GraphNode(StrEnum):
    PREPARE_TURN = "prepare_turn"
    UNDERSTAND_REQUEST = "understand_request"
    RESOLVE_ENTITIES = "resolve_entities"
    ASSESS_INFORMATION = "assess_information"
    ASK_USER = "ask_user"
    ROUTE_TASK = "route_task"
    PROCESS_TASK = "process_task"
    VALIDATE_RESULT = "validate_result"
    REVISE_RESULT = "revise_result"
    FINALIZE_RESPONSE = "finalize_response"


class InformationRoute(StrEnum):
    ASK_USER = "ask_user"
    ROUTE_TASK = "route_task"


class TaskRoute(StrEnum):
    PROCESS_TASK = "process_task"
    VALIDATE_RESULT = "validate_result"


class ValidationRoute(StrEnum):
    REVISE_RESULT = "revise_result"
    FINALIZE_RESPONSE = "finalize_response"


class ExecutionEventKind(StrEnum):
    NODE_COMPLETED = "node_completed"
    TOOL_CALLED = "tool_called"
    LIMIT_REACHED = "limit_reached"
    ERROR = "error"


class ChatMessage(AgentModel):
    message_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    role: MessageRole
    content: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    created_at: datetime = Field(default_factory=UtcClock.now)


class SourcedValue(AgentModel):
    value: str = Field(min_length=1)
    origin: ValueOrigin


class UserProfile(AgentModel):
    concerns: list[SourcedValue] = Field(default_factory=list)
    preferences: list[SourcedValue] = Field(default_factory=list)
    experiences: list[SourcedValue] = Field(default_factory=list)


class PendingQuestion(AgentModel):
    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    target_field: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    original_intents: list[Intent] = Field(min_length=1)
    original_request: ParsedRequest | None = None


class ParsedRequest(AgentModel):
    intents: list[Intent] = Field(min_length=1)
    query: str = Field(min_length=1)
    category: ProductCategory | None = None
    texture: ProductTexture | None = None
    skin_feel: ProductSkinFeel | None = None
    unsupported_product_conditions: list[str] = Field(default_factory=list)
    referenced_candidate_number: int | None = Field(default=None, ge=1)
    rejected_candidate_numbers: list[int] = Field(default_factory=list)
    excluded_weekdays: list[Weekday] = Field(default_factory=list)
    reported_experiences: list[str] = Field(default_factory=list)
    is_modification: bool = False
    pending_answer: bool = False
    ingredient_mentions: list[str] = Field(default_factory=list)
    known_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)


class TaskContext(AgentModel):
    """요약이 잘려도 유지해야 하는 방별 명시적 작업 조건."""

    search_filters: ProductSearchFilters = Field(default_factory=ProductSearchFilters)
    excluded_weekdays: list[Weekday] = Field(default_factory=list)
    rejected_product_ids: list[str] = Field(default_factory=list)
    evidence_target_ids: list[str] = Field(default_factory=list)
    evidence_combination_target_ids: list[str] = Field(default_factory=list)
    evidence_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)


class ResolvedEntities(AgentModel):
    products: list[ProductRecord] = Field(default_factory=list)
    ingredient_ids: list[str] = Field(default_factory=list)
    unresolved_names: list[str] = Field(default_factory=list)


class Citation(AgentModel):
    source_type: EvidenceSourceType = EvidenceSourceType.UNKNOWN
    text_kind: EvidenceTextKind = EvidenceTextKind.SUMMARY
    scope: EvidenceScope = EvidenceScope.INGREDIENT
    jurisdiction: str | None = None
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    document_version: str | None = Field(default=None, min_length=1)
    url: str | None = None
    is_demo: bool = True


class EvidenceAnswer(AgentModel):
    answer_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    is_demo: bool = True
    assessments: list[ApplicabilityAssessment] = Field(default_factory=list)
    generated: RagQueryResult | None = None


class RoutineSaveHandoff(AgentModel):
    """백엔드가 권한과 버전을 검증한 뒤 저장할 대상이며 저장 영수증이 아니다."""

    routine_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    is_demo: bool


Artifact = ProductCandidateSet | RoutinePlan | EvidenceAnswer


class UnresolvedItem(AgentModel):
    kind: UnresolvedKind
    detail: str = Field(min_length=1)
    retryable: bool = False


class ConversationSummary(AgentModel):
    content: str = Field(min_length=1)
    version: int = Field(ge=1)
    covered_through_sequence: int = Field(ge=1)


class ExecutionEvent(AgentModel):
    node: GraphNode
    kind: ExecutionEventKind
    detail: str = Field(min_length=1)


class ExecutionLimits(AgentModel):
    max_tool_calls: int = Field(default=DEFAULT_MAX_TOOL_CALLS, ge=1)
    max_revisions: int = Field(default=DEFAULT_MAX_REVISIONS, ge=0)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    recursion_limit: int = Field(default=DEFAULT_RECURSION_LIMIT, ge=10)


class ContextLimits(AgentModel):
    recent_message_limit: int = Field(default=DEFAULT_CONTEXT_MESSAGE_LIMIT, ge=1)
    summary_trigger: int = Field(default=DEFAULT_SUMMARY_TRIGGER, ge=2)
    summary_char_limit: int = Field(default=DEFAULT_SUMMARY_CHAR_LIMIT, ge=1)
    message_char_limit: int = Field(default=DEFAULT_MESSAGE_CHAR_LIMIT, ge=1)


class ChatTurnInput(AgentModel):
    chat_room_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    candidate_set_id: str | None = None
    routine_version: int | None = Field(default=None, ge=1)


class AuthenticatedChatContext(AgentModel):
    actor_id: str = Field(min_length=1)
    chat_room_id: str = Field(min_length=1)


class ChatServiceRequest(AgentModel):
    auth: AuthenticatedChatContext
    turn: ChatTurnInput


class ChatTurnOutput(AgentModel):
    chat_room_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    assistant_message_id: str = Field(min_length=1)
    status: ChatStatus
    message: str = Field(min_length=1)
    intents: list[Intent] = Field(default_factory=list)
    follow_up_question: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
    error_code: ErrorCode | None = None
    retryable: bool = False
    save_handoff: RoutineSaveHandoff | None = None


class RoomLookupRequest(AgentModel):
    actor_id: str = Field(min_length=1)
    chat_room_id: str = Field(min_length=1)


class AuthorizedRoom(AgentModel):
    actor_id: str = Field(min_length=1)
    chat_room_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


class RegisterRoomRequest(AgentModel):
    actor_id: str = Field(min_length=1)
    chat_room_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


class TurnIdentifiers(AgentModel):
    user_message_id: str = Field(min_length=1)
    assistant_message_id: str = Field(min_length=1)


class BeginTurnRequest(AgentModel):
    room: AuthorizedRoom
    turn: ChatTurnInput
    identifiers: TurnIdentifiers
    input_fingerprint: str = Field(min_length=1)


class SessionSnapshot(AgentModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    profile: UserProfile = Field(default_factory=UserProfile)
    task_context: TaskContext = Field(default_factory=TaskContext)
    pending_question: PendingQuestion | None = None
    candidate_set: ProductCandidateSet | None = None
    routine: RoutinePlan | None = None
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    summary: ConversationSummary | None = None
    schema_version: int = Field(default=1, ge=1)
    source_revision: int = Field(default=0, ge=0)
    last_completed_request_id: str | None = None


class BeginTurnResult(AgentModel):
    status: TurnBeginStatus
    output: ChatTurnOutput | None = None
    snapshot: SessionSnapshot | None = None
    user_message: ChatMessage | None = None


class SessionContextRequest(AgentModel):
    room: AuthorizedRoom


class SessionContextResult(AgentModel):
    snapshot: SessionSnapshot | None = None


class StageTurnResultRequest(AgentModel):
    room: AuthorizedRoom
    request_id: str = Field(min_length=1)
    output: ChatTurnOutput
    snapshot: SessionSnapshot


class CompleteTurnRequest(StageTurnResultRequest):
    """스테이징된 응답과 스냅샷을 공식 히스토리로 확정한다."""


class MarkTurnFailedRequest(AgentModel):
    room: AuthorizedRoom
    request_id: str = Field(min_length=1)
    failure_code: TurnFailureCode
    detail: str = Field(min_length=1)
    retryable: bool


class MessagePageRequest(AgentModel):
    room: AuthorizedRoom
    after_sequence: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_CONTEXT_MESSAGE_LIMIT, ge=1)


class MessagePage(AgentModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    has_more: bool = False


class ArtifactLookupRequest(AgentModel):
    room: AuthorizedRoom
    candidate_set_id: str | None = None
    routine_id: str | None = None
    routine_version: int | None = Field(default=None, ge=1)


class ArtifactLookupResult(AgentModel):
    artifacts: list[Artifact] = Field(default_factory=list)


class SaveSummaryRequest(AgentModel):
    room: AuthorizedRoom
    summary: ConversationSummary
    expected_revision: int = Field(ge=0)


class SaveSummaryResult(AgentModel):
    status: SummarySaveStatus
    source_revision: int = Field(ge=0)


class LlmContext(AgentModel):
    summary: ConversationSummary | None = None
    recent_messages: list[ChatMessage] = Field(default_factory=list)
    pending_question: PendingQuestion | None = None
    candidate_set: ProductCandidateSet | None = None
    routine: RoutinePlan | None = None
    profile: UserProfile = Field(default_factory=UserProfile)
    task_context: TaskContext = Field(default_factory=TaskContext)


class UnderstandingRequest(AgentModel):
    message: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    context: LlmContext
    product_taxonomy: ProductTaxonomy


class AgentInvocation(AgentModel):
    chat_room_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    turn_input: ChatTurnInput
    identifiers: TurnIdentifiers
    execution_limits: ExecutionLimits
    context_limits: ContextLimits
    restored_snapshot: SessionSnapshot | None = None
    user_message: ChatMessage | None = None


class AgentState(AgentModel):
    chat_room_id: str = ""
    thread_id: str = ""
    turn_input: ChatTurnInput | None = None
    identifiers: TurnIdentifiers | None = None
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    context_limits: ContextLimits = Field(default_factory=ContextLimits)
    restored_snapshot: SessionSnapshot | None = None
    user_message: ChatMessage | None = None

    messages: list[ChatMessage] = Field(default_factory=list)
    profile: UserProfile = Field(default_factory=UserProfile)
    task_context: TaskContext = Field(default_factory=TaskContext)
    pending_question: PendingQuestion | None = None
    candidate_set: ProductCandidateSet | None = None
    routine: RoutinePlan | None = None
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    summary: ConversationSummary | None = None

    parsed_request: ParsedRequest | None = None
    resolved_entities: ResolvedEntities = Field(default_factory=ResolvedEntities)
    task_queue: list[Intent] = Field(default_factory=list)
    current_intent: Intent | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
    response_parts: list[str] = Field(default_factory=list)
    follow_up_question: str | None = None
    status: ChatStatus = ChatStatus.COMPLETED
    error_code: ErrorCode | None = None
    retryable: bool = False
    tool_call_count: int = Field(default=0, ge=0)
    revision_count: int = Field(default=0, ge=0)
    needs_revision: bool = False
    started_at: datetime = Field(default_factory=UtcClock.now)
    events: list[ExecutionEvent] = Field(default_factory=list)
    output: ChatTurnOutput | None = None
    save_handoff: RoutineSaveHandoff | None = None

    def to_session_snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            messages=self.messages,
            profile=self.profile,
            task_context=self.task_context,
            pending_question=self.pending_question,
            candidate_set=self.candidate_set,
            routine=self.routine,
            evidence=self.evidence,
            summary=self.summary,
            last_completed_request_id=(self.turn_input.request_id if self.turn_input else None),
        )


class GraphInvocationRequest(AgentModel):
    invocation: AgentInvocation
    recursion_limit: int = Field(ge=10)


class GraphInvocationResult(AgentModel):
    state: AgentState
