/**
 * `POST /chat` 요청·응답 타입의 zod 미러.
 *
 * 원본은 백엔드가 소유한다. 요청/응답 봉투는 `backend/schemas/chat.py`, 중첩 타입은
 * `agent/schemas.py` 와 `agent/rag/schemas.py` 다. 여기서는 그대로 옮겨 두기만 하며,
 * 백엔드가 필드를 바꾸면 같이 바꿔야 한다. 어긋나면 `api/chat.ts` 가 응답 파싱 단계에서
 * 바로 실패해서 알 수 있다. 계약서: `docs/contracts/front-to-backend.md`.
 *
 * 서버(FastAPI `response_model`)는 `None` 인 필드와 기본값이 있는 필드도 항상 내려주므로
 * nullable 만 표시하고 optional 로 두지 않는다. 필드가 빠져 오면 파싱이 실패해서
 * 계약이 어긋난 것을 바로 알 수 있다(규칙 7).
 */

import { z } from "zod";

import {
  ApplicabilityStatus,
  ChatErrorCode,
  ChatIntent,
  ChatTurnStatus,
  ConstraintSource,
  DayPeriod,
  EvidenceReviewStatus,
  EvidenceScope,
  EvidenceSourceType,
  EvidenceTextKind,
  RegulateType,
  RegulatoryConfidence,
  UnresolvedKind,
  UnverifiableReason,
  Weekday,
} from "../constants/chat";

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
