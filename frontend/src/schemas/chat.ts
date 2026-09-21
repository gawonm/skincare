/**
 * `POST /chat` 요청·응답(SSE) 타입의 zod 미러.
 *
 * 원본은 백엔드가 소유한다(`backend/schemas/chat.py`). 여기서는 계약서
 * `docs/contracts/front-to-backend.md` 초안을 1:1 로 베껴 두기만 한다. 백엔드가
 * 필드를 바꾸면 여기도 같이 바꿔야 하며, 그 전까지는 컴파일이 통과해도 런타임에서 어긋난다.
 *
 * 계약서 "아직 안 정한 것" 에 걸리는 부분은 초안 형태 그대로 두고 `TODO(contract)` 로
 * 표시한다. 임의로 확정하지 않는다 (CLAUDE.md 규칙 3).
 */

import { z } from "zod";

import {
  ApplicabilityStatus,
  ChatErrorCode,
  ChatIntent,
  ChatRole,
  ChatTurnStatus,
  ConstraintSource,
  DayPeriod,
  EvidenceReviewStatus,
  EvidenceScope,
  EvidenceSourceType,
  EvidenceTextKind,
  RegulateType,
  RegulatoryConfidence,
  SseEventName,
  UnresolvedKind,
  UnverifiableReason,
  Weekday,
} from "../constants/chat";

/** 계약서 `Role`(StrEnum) 미러. */
export const roleSchema = z.nativeEnum(ChatRole);

/**
 * 계약서 `ChatMessage` 미러.
 * 화면 세션의 메모리(상태 배열)에만 쌓이고 서버·에이전트는 저장하지 않는다.
 */
export const chatMessageSchema = z.object({
  role: roleSchema,
  content: z.string(),
});
export type ChatMessage = z.infer<typeof chatMessageSchema>;

/**
 * 계약서 `ChatRequest` 미러.
 * 현재 화면 세션의 전체 대화. 마지막 원소가 방금 보낸 사용자 메시지다.
 */
export const chatRequestSchema = z.object({
  messages: z.array(chatMessageSchema),
});
export type ChatRequest = z.infer<typeof chatRequestSchema>;

// ---------------------------------------------------------------------------
// SSE 이벤트별 data 형태 (계약서 "출력 — SSE 이벤트")
// ---------------------------------------------------------------------------

export const stageEventDataSchema = z.object({
  // TODO(contract): stage 문구를 서버가 완성해 보내는지, 코드값만 보내고 프론트가
  //  문구를 갖는지 미정. 지금은 완성 문구(label)가 온다고 보고 미러링한다.
  label: z.string(),
});
export type StageEventData = z.infer<typeof stageEventDataSchema>;

export const tokenEventDataSchema = z.object({
  text: z.string(),
});
export type TokenEventData = z.infer<typeof tokenEventDataSchema>;

export const warningEventDataSchema = z.object({
  // TODO(contract): 경고를 별도 `warning` 이벤트로 줄지 `token` 본문에 마크업으로
  //  섞을지 미정. 지금은 별도 이벤트로 온다고 보고 미러링한다.
  text: z.string(),
});
export type WarningEventData = z.infer<typeof warningEventDataSchema>;

export const sourceItemSchema = z.object({
  // TODO(contract): 라벨 + 건수로 충분한지, 성분노트로 가는 링크나 id 가 필요한지 미정.
  label: z.string(),
  count: z.number().int().nonnegative(),
});
export type SourceItem = z.infer<typeof sourceItemSchema>;

export const sourcesEventDataSchema = z.object({
  items: z.array(sourceItemSchema),
});
export type SourcesEventData = z.infer<typeof sourcesEventDataSchema>;

export const doneEventDataSchema = z.object({});
export type DoneEventData = z.infer<typeof doneEventDataSchema>;

export const errorEventDataSchema = z.object({
  detail: z.string(),
});
export type ErrorEventData = z.infer<typeof errorEventDataSchema>;

/**
 * 파싱이 끝난 SSE 이벤트 한 건. `event` 이름으로 구분되는 판별 유니온.
 * 목(`api/chatMock.ts`)이 이 형태를 yield 하고, 훅(`hooks/useChat.ts`)이 소비한다.
 *
 * 판별자는 문자열 리터럴이 아니라 `SseEventName` enum 멤버로 둔다. 문자열 enum 멤버는
 * 대응 리터럴 타입과 호환되지 않아서(예: `SseEventName.Stage` ↔ `"stage"`), 섞어 쓰면
 * yield/switch 양쪽에서 타입이 어긋난다.
 */
export type ChatSseEvent =
  | { event: SseEventName.Stage; data: StageEventData }
  | { event: SseEventName.Token; data: TokenEventData }
  | { event: SseEventName.Warning; data: WarningEventData }
  | { event: SseEventName.Sources; data: SourcesEventData }
  | { event: SseEventName.Done; data: DoneEventData }
  | { event: SseEventName.Error; data: ErrorEventData };

// ===========================================================================
// 단일 JSON 응답(`POST /chat`) 미러.
//
// 원본: 요청/응답 봉투는 `backend/schemas/chat.py`, 중첩 타입은 `agent/schemas.py` 와
// `agent/rag/schemas.py`. 위쪽의 SSE 시절 타입은 훅·화면을 갈아엎는 커밋에서 지운다.
//
// 서버(FastAPI `response_model`)는 `None` 인 필드와 기본값이 있는 필드도 항상 내려주므로
// nullable 만 표시하고 optional 로 두지 않는다. 필드가 빠져 오면 파싱이 실패해서
// 계약이 어긋난 것을 바로 알 수 있다(규칙 7).
// ===========================================================================

/** `ChatSendMessageRequest` 미러. 방 식별자는 서버가 로그인 사용자로 찾으므로 없다. */
export const chatSendRequestSchema = z.object({
  request_id: z.string().min(1),
  message: z.string().min(1),
  // 채우는 시점이 계약서 "아직 안 정한 것" 1번이라 지금은 보내지 않는다. 필드만 미러링한다.
  candidate_set_id: z.string().nullable().optional(),
  routine_version: z.number().int().min(1).nullable().optional(),
});
export type ChatSendRequest = z.infer<typeof chatSendRequestSchema>;

// --- citations ---

export const citationSchema = z.object({
  source_type: z.nativeEnum(EvidenceSourceType),
  text_kind: z.nativeEnum(EvidenceTextKind),
  scope: z.nativeEnum(EvidenceScope),
  jurisdiction: z.string().nullable(),
  evidence_id: z.string().min(1),
  source_id: z.string().min(1),
  locator: z.string().min(1),
  source_title: z.string().min(1),
  document_version: z.string().nullable(),
  url: z.string().nullable(),
  is_demo: z.boolean(),
});
export type Citation = z.infer<typeof citationSchema>;

// --- artifacts ---

const evidenceConditionsSchema = z.object({
  concentration: z.string().nullable(),
  formulation: z.string().nullable(),
  route: z.string().nullable(),
  usage: z.string().nullable(),
  duration: z.string().nullable(),
  ph: z.string().nullable(),
  jurisdiction: z.string().nullable(),
});

const evidenceRecordSchema = z.object({
  source_type: z.nativeEnum(EvidenceSourceType),
  text_kind: z.nativeEnum(EvidenceTextKind),
  scope: z.nativeEnum(EvidenceScope),
  topic: z.string().nullable(),
  jurisdiction: z.string().nullable(),
  raw_conditions: z.string().nullable(),
  source_reference: z.string().nullable(),
  regulatory_confidence: z.nativeEnum(RegulatoryConfidence).nullable(),
  regulate_type: z.nativeEnum(RegulateType).nullable(),
  published_at: z.string().nullable(),
  collected_at: z.string().nullable(),
  evidence_id: z.string().min(1),
  source_id: z.string().min(1),
  source_title: z.string().min(1),
  document_version: z.string().nullable(),
  text: z.string().min(1),
  locator: z.string().min(1),
  target_ids: z.array(z.string()),
  conditions: evidenceConditionsSchema,
  review_status: z.nativeEnum(EvidenceReviewStatus),
  url: z.string().nullable(),
  is_demo: z.boolean(),
});

const evidenceBackedStatementSchema = z.object({
  sentence: z.string().min(1),
  sources: z.array(evidenceRecordSchema).min(1),
});

const ingredientVerificationResultSchema = z.object({
  claims: z.array(evidenceBackedStatementSchema),
  unverifiable_reason: z.nativeEnum(UnverifiableReason).nullable(),
});

const ragQueryResultSchema = z.object({
  per_target: z.array(
    z.object({
      target_id: z.string(),
      result: ingredientVerificationResultSchema,
    }),
  ),
  combination: ingredientVerificationResultSchema.nullable(),
  free_text: ingredientVerificationResultSchema.nullable(),
});

/** `ProductCategory`/`ProductTexture`/`ProductSkinFeel` 는 모두 같은 모양이다. */
const productTaxonomyItemSchema = z.object({
  code: z.string().min(1),
  name: z.string().min(1),
  aliases: z.array(z.string()),
});

const productRecordSchema = z.object({
  product_id: z.string().min(1),
  version: z.string().nullable(),
  name: z.string().min(1),
  category: productTaxonomyItemSchema.nullable(),
  texture: productTaxonomyItemSchema.nullable(),
  skin_feel: productTaxonomyItemSchema.nullable(),
  ingredient_ids: z.array(z.string()),
  directions: z.string().nullable(),
  source_id: z.string().min(1),
  checked_at: z.string().min(1),
  is_demo: z.boolean(),
});

/** 후보 상품 목록. */
export const productCandidateSetSchema = z.object({
  candidate_set_id: z.string().min(1),
  candidates: z.array(
    z.object({
      rank: z.number().int().min(1),
      product: productRecordSchema,
      reasons: z.array(z.string()),
      unresolved: z.array(z.string()),
    }),
  ),
  is_demo: z.boolean(),
});
export type ProductCandidateSet = z.infer<typeof productCandidateSetSchema>;

/** 루틴. */
export const routinePlanSchema = z.object({
  routine_id: z.string().min(1),
  version: z.number().int().min(1),
  placements: z.array(
    z.object({
      weekday: z.nativeEnum(Weekday),
      period: z.nativeEnum(DayPeriod),
      product_id: z.string().min(1),
      product_name: z.string().min(1),
      order: z.number().int().min(1),
      reason: z.string().min(1),
    }),
  ),
  constraints: z.array(
    z.object({
      description: z.string().min(1),
      source: z.nativeEnum(ConstraintSource),
      source_id: z.string().nullable(),
    }),
  ),
  changes: z.array(z.string()),
  is_demo: z.boolean(),
});
export type RoutinePlan = z.infer<typeof routinePlanSchema>;

/** 근거 답변. */
export const evidenceAnswerSchema = z.object({
  answer_id: z.string().min(1),
  subject: z.string().min(1),
  summary: z.string().min(1),
  evidence_ids: z.array(z.string()),
  is_demo: z.boolean(),
  assessments: z.array(
    z.object({
      evidence_id: z.string().min(1),
      status: z.nativeEnum(ApplicabilityStatus),
      reasons: z.array(z.string()),
    }),
  ),
  generated: ragQueryResultSchema.nullable(),
});
export type EvidenceAnswer = z.infer<typeof evidenceAnswerSchema>;

/**
 * 서버의 `Artifact = ProductCandidateSet | RoutinePlan | EvidenceAnswer` 는 종류를 알려 주는
 * 태그 필드가 없다. 세 타입이 서로 다른 필수 키(`candidate_set_id`/`routine_id`/`answer_id`)를
 * 가져서 zod 유니온이 그 키로 구분한다. 종류를 구분해 쓸 때도 이 키 유무로 좁힌다.
 */
export const artifactSchema = z.union([
  productCandidateSetSchema,
  routinePlanSchema,
  evidenceAnswerSchema,
]);
export type Artifact = z.infer<typeof artifactSchema>;

// --- 응답 봉투 ---

export const unresolvedItemSchema = z.object({
  kind: z.nativeEnum(UnresolvedKind),
  detail: z.string().min(1),
  retryable: z.boolean(),
});
export type UnresolvedItem = z.infer<typeof unresolvedItemSchema>;

export const routineSaveHandoffSchema = z.object({
  routine_id: z.string().min(1),
  version: z.number().int().min(1),
  is_demo: z.boolean(),
});
export type RoutineSaveHandoff = z.infer<typeof routineSaveHandoffSchema>;

/** `ChatTurnResponse` 미러. */
export const chatTurnResponseSchema = z.object({
  chat_room_id: z.string().min(1),
  request_id: z.string().min(1),
  assistant_message_id: z.string().min(1),
  status: z.nativeEnum(ChatTurnStatus),
  message: z.string().min(1),
  intents: z.array(z.nativeEnum(ChatIntent)),
  follow_up_question: z.string().nullable(),
  artifacts: z.array(artifactSchema),
  citations: z.array(citationSchema),
  unresolved: z.array(unresolvedItemSchema),
  error_code: z.nativeEnum(ChatErrorCode).nullable(),
  retryable: z.boolean(),
  save_handoff: routineSaveHandoffSchema.nullable(),
});
export type ChatTurnResponse = z.infer<typeof chatTurnResponseSchema>;
