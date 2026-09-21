/**
 * AI 채팅 화면이 공유하는 상수.
 *
 * 규칙 9(매직 넘버·문자열 금지)에 따라 라우트/엔드포인트 경로, SSE 이벤트 이름,
 * placeholder 문구, 하단 탭 목록을 한곳에 모은다. SSE 이벤트 이름과 역할 값은
 * 계약서 `docs/contracts/front-to-backend.md` 와 맞물린다.
 */

/** 프론트 라우트 경로. */
export enum ChatRoute {
  Chat = "/chat",
}

/**
 * 백엔드 엔드포인트. 목 단계에선 네트워크를 타지 않아 쓰이지 않고,
 * `api/chatMock.ts` → `api/chat.ts` 교체 시 실제 fetch 대상이 된다.
 */
export enum ChatEndpoint {
  Chat = "/chat",
}

/** 계약서 `Role`(StrEnum) 미러. */
export enum ChatRole {
  User = "user",
  Assistant = "assistant",
}

/**
 * `ChatTurnResponse.status` 미러(`agent/schemas.py` 의 `ChatStatus`).
 * 훅이 쓰는 화면 상태(`ChatStatus`)와 이름이 겹치지 않게 `ChatTurnStatus` 로 둔다.
 */
export enum ChatTurnStatus {
  Completed = "completed",
  NeedsInput = "needs_input",
  Partial = "partial",
  Error = "error",
}

/**
 * `ChatTurnResponse.error_code` 미러(`agent/schemas.py` 의 `ErrorCode`).
 * 의미는 `docs/contracts/backend-to-agent.md` 6절을 따른다.
 */
export enum ChatErrorCode {
  RoomNotFound = "room_not_found",
  RoomForbidden = "room_forbidden",
  RequestConflict = "request_conflict",
  RequestInProgress = "request_in_progress",
  GraphExecutionFailed = "graph_execution_failed",
  ResponseSaveFailed = "response_save_failed",
  ExecutionLimitReached = "execution_limit_reached",
  ToolFailed = "tool_failed",
}

/** `POST /chat` 이 쓰는 HTTP 상태코드(계약서 "실패했을 때"). */
export enum ChatHttpStatus {
  Unauthorized = 401,
  UnprocessableEntity = 422,
  ServiceUnavailable = 503,
}

/** `agent/schemas.py` 의 `Intent` 미러. */
export enum ChatIntent {
  ProductDiscovery = "product_discovery",
  RoutinePlanning = "routine_planning",
  EvidenceQa = "evidence_qa",
  GeneralChat = "general_chat",
  OutOfScope = "out_of_scope",
  Clarification = "clarification",
  RoutineSave = "routine_save",
}

/** `agent/schemas.py` 의 `UnresolvedKind` 미러. */
export enum UnresolvedKind {
  MissingInformation = "missing_information",
  UnsupportedCondition = "unsupported_condition",
  NoEvidence = "no_evidence",
  ToolFailure = "tool_failure",
  Conflict = "conflict",
}

// ---------------------------------------------------------------------------
// artifacts / citations 안쪽 값. 원본은 `agent/rag/schemas.py` 이고 여기서는 미러링만 한다.
// ---------------------------------------------------------------------------

export enum EvidenceSourceType {
  Unknown = "unknown",
  Demo = "demo",
  IngredientKnowledge = "ingredient_knowledge",
  MfdsRestrictedIngredient = "mfds_restricted_ingredient",
  Cir = "cir",
  Paper = "paper",
  Hetionet = "hetionet",
}

export enum EvidenceTextKind {
  Excerpt = "excerpt",
  Summary = "summary",
}

export enum EvidenceScope {
  Ingredient = "ingredient",
  Product = "product",
  Pair = "pair",
  Association = "association",
}

export enum EvidenceReviewStatus {
  Verified = "verified",
  Unreviewed = "unreviewed",
  Demo = "demo",
}

export enum RegulatoryConfidence {
  Verified = "verified",
  Unverified = "unverified",
}

export enum RegulateType {
  Prohibited = "prohibited",
  Limited = "limited",
}

export enum ApplicabilityStatus {
  Applicable = "applicable",
  Limited = "limited",
  NotApplicable = "not_applicable",
  Unknown = "unknown",
}

export enum UnverifiableReason {
  NoEvidenceFound = "no_evidence_found",
  UnreviewedEvidence = "unreviewed_evidence",
  NotRelevantToQuestion = "not_relevant_to_question",
  MissingCombinationEvidence = "missing_combination_evidence",
  CitationValidationFailed = "citation_validation_failed",
}

export enum ConstraintSource {
  ProductDirections = "product_directions",
  User = "user",
  ServicePolicy = "service_policy",
}

export enum Weekday {
  Monday = "monday",
  Tuesday = "tuesday",
  Wednesday = "wednesday",
  Thursday = "thursday",
  Friday = "friday",
  Saturday = "saturday",
  Sunday = "sunday",
}

export enum DayPeriod {
  Morning = "morning",
  Evening = "evening",
}

/**
 * 계약서 "출력 — SSE 이벤트"의 event 이름.
 * 각 event 의 data 형태는 아직 미정이라 `schemas/chat.ts` 에서 초안 형태로만 미러링한다.
 */
export enum SseEventName {
  Stage = "stage",
  Token = "token",
  Warning = "warning",
  Sources = "sources",
  Done = "done",
  Error = "error",
}

/** 훅이 노출하는 스트리밍 상태. */
export enum ChatStatus {
  Idle = "idle",
  Streaming = "streaming",
}

/** 입력창 placeholder. 화면 상태별로 다르다(시안 04A/04B/04C). */
export enum ChatPlaceholder {
  Initial = "무엇이든 물어보세요.",
  Conversation = "성분 이름이나 궁금한 점을 입력",
  Responding = "계속 물어볼 수 있어요.",
}

/**
 * 진행 상태 문구 폴백(시안 04C).
 * TODO(contract): docs/contracts/front-to-backend.md 확정 후 —
 *  stage 문구를 서버가 완성해 보내는지, 코드값만 보내고 프론트가 문구 테이블을 갖는지 미정.
 */
export const DEFAULT_STAGE_LABEL = "입력하신 요청을 확인하고 있어요";

/**
 * 04A 최초 진입 화면의 안내 문구.
 * 이름은 로그인 시에만 있어 지금은 이름 없는 폴백만 쓴다.
 */
export const CHAT_EMPTY_STATE = {
  eyebrow: "SKINCARE ASSISTANT",
  // TODO: useAuth(GET /auth/me) 연결 후 로그인 사용자에겐 "안녕하세요 {name}님".
  greetingLine1: "안녕하세요",
  greetingLine2: "무엇이 궁금하신가요?",
  subtext: "성분 조합부터 피부 고민까지\n필요한 정보를 쉽고 빠르게 찾아드려요.",
} as const;

/** 하단 탭 키. */
export enum NavTabKey {
  Home = "home",
  Chat = "chat",
  Schedule = "schedule",
  Profile = "profile",
}

export interface NavTabItem {
  key: NavTabKey;
  label: string;
  /** 이번 범위에선 Chat 만 true. 나머지는 표시만 하고 라우팅하지 않는다. */
  enabled: boolean;
}

/** 하단 탭 바 구성. 시안 순서(홈 · AI 채팅 · 스케줄 · 프로필) 그대로. */
export const NAV_TABS: NavTabItem[] = [
  { key: NavTabKey.Home, label: "홈", enabled: false },
  { key: NavTabKey.Chat, label: "AI 채팅", enabled: true },
  { key: NavTabKey.Schedule, label: "스케줄", enabled: false },
  { key: NavTabKey.Profile, label: "프로필", enabled: false },
];
