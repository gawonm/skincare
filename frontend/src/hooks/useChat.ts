/**
 * AI 채팅 화면의 상태와 `POST /chat` 호출을 한곳에 모은 훅.
 *
 * 응답은 SSE 가 아니라 완성된 단일 JSON 이라서 "요청 중 → 응답" 두 단계뿐이다. 정지 버튼으로
 * 대기를 끊어야 해서 `useMutation` 대신 `AbortController` 를 직접 들고 있다.
 *
 * 대화는 서버가 저장하지만 이전 메시지를 다시 그리는 API 는 없다(계약서 "범위"). 그래서
 * 이 훅의 `turns` 는 이번 화면 세션에서 오간 것만 담고, 화면을 벗어나면 사라진다.
 * 다시 들어와도 Agent 는 이전 대화를 기억한다.
 */

import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ChatApi, ChatResponseParseError } from "../api/chat";
import { ApiError } from "../api/client";
import {
  CHAT_FAILURE_MESSAGE,
  ChatHttpStatus,
  ChatRole,
  ChatRoute,
  ChatStatus,
  ChatTurnStatus,
  ChatTurnTone,
} from "../constants/chat";
import type { ChatTurnResponse } from "../schemas/chat";

/** 화면에 그릴 대화 한 턴. */
export interface ChatTurn {
  role: ChatRole;
  content: string;
  tone: ChatTurnTone;
  /**
   * 서버가 돌려준 응답 원본. artifacts/citations 등을 화면이 꺼내 쓸 수 있게 통째로 둔다.
   * 사용자 턴과 프론트가 만든 실패 안내 턴에서는 null.
   */
  response: ChatTurnResponse | null;
}

/** 재시도할 요청. 같은 `request_id` 를 그대로 다시 보내야 서버가 같은 요청으로 인식한다. */
interface RetryTarget {
  requestId: string;
  content: string;
}

/** 요청이 실패했을 때 화면에 보여 줄 문구와 재시도 가능 여부. */
interface ChatFailureInfo {
  message: string;
  retryable: boolean;
}

export interface UseChatResult {
  turns: ChatTurn[];
  status: ChatStatus;
  /** 마지막 실패를 같은 `request_id` 로 다시 보낼 수 있는지. */
  canRetry: boolean;
  sendMessage: (content: string) => void;
  retry: () => void;
  /** 응답 대기를 끊는다(서버 처리는 계속될 수 있다). 대기 중이 아니면 아무 일도 하지 않는다. */
  stopSending: () => void;
}

/** 요청 결과(예외·응답)를 화면 문구와 턴으로 바꾼다. 401 은 여기 오기 전에 훅이 로그인으로 보낸다. */
class ChatResponseMapper {
  static describe(cause: unknown): ChatFailureInfo {
    if (cause instanceof ChatResponseParseError) {
      // 사용자에게는 짧게, 어느 필드가 틀렸는지는 개발자가 볼 수 있게 콘솔에 남긴다.
      console.error(cause.message, cause);
      return { message: CHAT_FAILURE_MESSAGE.responseMismatch, retryable: false };
    }
    if (cause instanceof ApiError) {
      // 서버에 닿지 못한 경우(0)와 Agent 미준비(503)는 잠시 뒤 나아질 수 있어 다시 시도할 수 있다.
      // 같은 request_id 를 다시 보내도 서버가 같은 요청으로 다루므로 중복 처리되지 않는다.
      const retryable =
        cause.isNetworkError || cause.status === ChatHttpStatus.ServiceUnavailable;
      return { message: cause.message, retryable };
    }
    console.error("채팅 요청 중 예상하지 못한 오류", cause);
    return { message: CHAT_FAILURE_MESSAGE.unexpected, retryable: false };
  }

  /**
   * 서버 응답을 대화창 턴으로 만든다.
   * `needs_input` 은 Agent 가 되묻는 질문을 이미 `message` 안에 넣어 보내므로, 질문이
   * `message` 에 없을 때만 덧붙여 같은 문장이 두 번 나오지 않게 한다.
   */
  static toTurn(response: ChatTurnResponse): ChatTurn {
    let content = response.message;
    if (
      response.status === ChatTurnStatus.NeedsInput &&
      response.follow_up_question !== null &&
      !content.includes(response.follow_up_question)
    ) {
      content = `${content}\n\n${response.follow_up_question}`;
    }
    return {
      role: ChatRole.Assistant,
      content,
      tone:
        response.status === ChatTurnStatus.Error ? ChatTurnTone.Error : ChatTurnTone.Normal,
      response,
    };
  }
}

export function useChat(): UseChatResult {
  const navigate = useNavigate();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [status, setStatus] = useState<ChatStatus>(ChatStatus.Idle);
  const [retryTarget, setRetryTarget] = useState<RetryTarget | null>(null);

  // 진행 중인 요청을 끊기 위한 컨트롤러. 요청이 없으면 null.
  const abortRef = useRef<AbortController | null>(null);

  const stopSending = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const run = useCallback(
    async (target: RetryTarget): Promise<void> => {
      const controller = new AbortController();
      abortRef.current = controller;
      setStatus(ChatStatus.Sending);
      setRetryTarget(null);

      try {
        const response = await ChatApi.sendMessage(
          { request_id: target.requestId, message: target.content },
          controller.signal,
        );
        setTurns((prev) => [...prev, ChatResponseMapper.toTurn(response)]);
        if (response.status === ChatTurnStatus.Error && response.retryable) {
          setRetryTarget(target);
        }
      } catch (cause) {
        // 정지 버튼이나 화면 이탈로 끊은 경우. 실패로 보여 줄 것이 없다.
        if (controller.signal.aborted) {
          return;
        }
        if (cause instanceof ApiError && cause.status === ChatHttpStatus.Unauthorized) {
          navigate(ChatRoute.Login);
          return;
        }
        const failure = ChatResponseMapper.describe(cause);
        setTurns((prev) => [
          ...prev,
          {
            role: ChatRole.Assistant,
            content: failure.message,
            tone: ChatTurnTone.Error,
            response: null,
          },
        ]);
        if (failure.retryable) {
          setRetryTarget(target);
        }
      } finally {
        // 정지 후 곧바로 새 요청이 시작됐다면 그 요청의 컨트롤러를 지우지 않는다.
        if (abortRef.current === controller) {
          abortRef.current = null;
          setStatus(ChatStatus.Idle);
        }
      }
    },
    [navigate],
  );

  const sendMessage = useCallback(
    (raw: string) => {
      const content = raw.trim();
      // 빈 입력이나 응답 대기 중 재전송은 무시한다(같은 방에 동시에 두 턴이 들어가지 않게).
      if (content.length === 0 || status === ChatStatus.Sending) {
        return;
      }

      setTurns((prev) => [
        ...prev,
        { role: ChatRole.User, content, tone: ChatTurnTone.Normal, response: null },
      ]);
      // 재시도해도 같은 요청으로 인식되도록 발급은 사용자가 보낼 때 딱 한 번만 한다.
      void run({ requestId: crypto.randomUUID(), content });
    },
    [run, status],
  );

  const retry = useCallback(() => {
    if (retryTarget === null || status === ChatStatus.Sending) {
      return;
    }
    // 실패 안내는 다시 시도하는 순간 걷어 낸다. 사용자 말풍선은 그대로 두고 응답만 다시 기다린다.
    setTurns((prev) =>
      prev.length > 0 && prev[prev.length - 1].tone === ChatTurnTone.Error
        ? prev.slice(0, -1)
        : prev,
    );
    void run(retryTarget);
  }, [retryTarget, run, status]);

  return {
    turns,
    status,
    canRetry: retryTarget !== null,
    sendMessage,
    retry,
    stopSending,
  };
}
