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

import { ChatRole, SseEventName } from "../constants/chat";

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
