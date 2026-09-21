/**
 * `POST /chat` 요청 함수.
 *
 * 응답 타입의 원본은 백엔드(`backend/schemas/chat.py`)이고, 여기서는 zod 로 런타임 검증만
 * 한다. 백엔드와 프론트의 모양이 어긋나면 화면이 조용히 깨지지 않고 이 파일에서 바로
 * `ChatResponseParseError` 로 드러나게 하려는 것이다(규칙 7).
 *
 * 401/503 같은 HTTP 오류는 `fetchJson` 이 던지는 `ApiError` 를 그대로 올려 보낸다.
 * 401 을 로그인 화면으로 보낼지, 503 문구를 어떻게 보여 줄지는 호출부(훅)가 정한다.
 */

import { ZodError } from "zod";

import { ChatEndpoint } from "../constants/chat";
import { chatTurnResponseSchema } from "../schemas/chat";
import type { ChatSendRequest, ChatTurnResponse } from "../schemas/chat";
import { fetchJson } from "./client";

/** 서버가 200 을 줬지만 본문이 계약(`ChatTurnResponse`)과 맞지 않을 때의 예외. */
export class ChatResponseParseError extends Error {
  readonly issues: string;

  constructor(cause: ZodError) {
    // 어느 필드가 왜 틀렸는지 알아야 계약 불일치를 고칠 수 있어서 경로까지 문구에 넣는다.
    const issues = cause.issues
      .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
      .join("; ");
    super(`채팅 응답이 계약과 다릅니다: ${issues}`, { cause });
    this.name = "ChatResponseParseError";
    this.issues = issues;
  }
}

export class ChatApi {
  /**
   * 메시지 한 턴을 보내고 완성된 응답을 받는다.
   *
   * Agent 오류(`status: "error"`)는 예외가 아니라 정상 응답(200)으로 온다. 계약서가 그렇게
   * 정했으므로 여기서 예외로 바꾸지 않고, 상태별 처리는 호출부가 한다.
   */
  static async sendMessage(
    body: ChatSendRequest,
    signal?: AbortSignal,
  ): Promise<ChatTurnResponse> {
    const raw = await fetchJson<unknown>(ChatEndpoint.Chat, {
      method: "POST",
      body: JSON.stringify(body),
      // 정지 버튼과 화면 이탈 때 대기를 끊기 위한 신호. 서버 처리까지 취소하지는 못한다.
      signal,
    });

    const parsed = chatTurnResponseSchema.safeParse(raw);
    if (!parsed.success) {
      throw new ChatResponseParseError(parsed.error);
    }
    return parsed.data;
  }
}
