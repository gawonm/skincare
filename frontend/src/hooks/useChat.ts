/**
 * AI 채팅 화면의 상태와 목 스트림 연결을 한곳에 모은 훅.
 *
 * 데이터 접근(`api/chatMock.ts`)을 이 훅 뒤에 숨겨서, 나중에 실제 백엔드로 바꿀 때
 * 화면 컴포넌트는 건드리지 않고 이 파일과 `api/*` 만 손보면 되게 한다.
 * (auth 의 `api/auth.ts` + `hooks/useLogin.ts` 와 같은 구성. 다만 SSE 스트림이라
 *  TanStack Query 의 `useMutation` 대신 로컬 상태로 누적한다.)
 *
 * 대화 이력은 이 훅의 메모리에만 있다. 화면을 벗어나 언마운트되면 사라지는 것이
 * 계약서가 말하는 "초기화" 다. 서버·에이전트는 무상태다.
 */

import { useCallback, useRef, useState } from "react";

import { streamMockChatResponse } from "../api/chatMock";
import { ChatRole, ChatStatus, SseEventName } from "../constants/chat";
import type { ChatMessage, ChatRequest, SourceItem } from "../schemas/chat";

/**
 * 화면에 그릴 대화 한 턴.
 * 계약서 `ChatMessage`(역할 + 본문)에 더해, assistant 턴은 SSE 의 warning/sources
 * 이벤트 결과를 함께 들고 있다. 서버로 보낼 때는 역할 + 본문만 남기고 떼어낸다.
 */
export interface ChatTurn {
  role: ChatRole;
  content: string;
  warning: string | null;
  sources: SourceItem[] | null;
}

/** 스트리밍 중인 assistant 답변의 누적 상태. */
export interface StreamingTurn {
  /** 아직 본문 토큰이 오기 전 진행 상태 문구(시안 04C). 토큰이 오면 null 로 바뀐다. */
  stageLabel: string | null;
  content: string;
  warning: string | null;
  sources: SourceItem[] | null;
}

export interface UseChatResult {
  turns: ChatTurn[];
  /** status 가 Streaming 일 때만 값이 있다. */
  streaming: StreamingTurn | null;
  status: ChatStatus;
  /** 목/스트림 처리 중 발생한 오류 문구. 없으면 null. */
  error: string | null;
  sendMessage: (content: string) => void;
  stopStreaming: () => void;
}

export function useChat(): UseChatResult {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [streaming, setStreaming] = useState<StreamingTurn | null>(null);
  const [status, setStatus] = useState<ChatStatus>(ChatStatus.Idle);
  const [error, setError] = useState<string | null>(null);

  // 진행 중인 스트림을 취소하기 위한 컨트롤러. 스트림이 없으면 null.
  const abortRef = useRef<AbortController | null>(null);

  const stopStreaming = useCallback(() => {
    // 사용자가 정지를 눌렀거나 화면이 언마운트된 경우. 진행 중이 아니면 할 일 없음.
    abortRef.current?.abort();
  }, []);

  const sendMessage = useCallback(
    (raw: string) => {
      const content = raw.trim();
      // 빈 입력이나 응답 진행 중 재전송은 무시한다(중복 스트림 방지).
      if (content.length === 0 || status === ChatStatus.Streaming) {
        return;
      }

      const userTurn: ChatTurn = {
        role: ChatRole.User,
        content,
        warning: null,
        sources: null,
      };
      const history: ChatTurn[] = [...turns, userTurn];

      setTurns(history);
      setError(null);
      setStatus(ChatStatus.Streaming);
      setStreaming({ stageLabel: null, content: "", warning: null, sources: null });

      const controller = new AbortController();
      abortRef.current = controller;

      const request: ChatRequest = {
        // 서버에는 역할 + 본문만 보낸다. warning/sources 는 화면 표시용이라 뺀다.
        messages: history.map(
          (turn): ChatMessage => ({ role: turn.role, content: turn.content }),
        ),
      };

      // 누적값은 리렌더와 무관하게 최신 상태를 들고 있어야 하므로 지역 변수로 모은다.
      let text = "";
      let warning: string | null = null;
      let sources: SourceItem[] | null = null;

      const finalize = (): void => {
        // 토큰이 하나도 안 온 채 끊겼으면 빈 assistant 턴은 만들지 않는다.
        if (text.length > 0) {
          setTurns((prev) => [
            ...prev,
            { role: ChatRole.Assistant, content: text, warning, sources },
          ]);
        }
        setStreaming(null);
        setStatus(ChatStatus.Idle);
        abortRef.current = null;
      };

      const run = async (): Promise<void> => {
        try {
          for await (const sse of streamMockChatResponse(request, controller.signal)) {
            switch (sse.event) {
              case SseEventName.Stage:
                setStreaming({ stageLabel: sse.data.label, content: text, warning, sources });
                break;
              case SseEventName.Token:
                text += sse.data.text;
                setStreaming({ stageLabel: null, content: text, warning, sources });
                break;
              case SseEventName.Warning:
                warning = sse.data.text;
                setStreaming({ stageLabel: null, content: text, warning, sources });
                break;
              case SseEventName.Sources:
                sources = sse.data.items;
                setStreaming({ stageLabel: null, content: text, warning, sources });
                break;
              case SseEventName.Done:
                // 정상 종료. 남은 처리는 루프 밖 finalize 에서 한다.
                break;
              case SseEventName.Error:
                // TODO(contract): 에러 시 화면 상태(재시도 버튼, 부분 답변 유지 여부)는 미정.
                //  지금은 문구만 노출하고, 받은 부분 답변은 아래 finalize 에서 남긴다.
                setError(sse.data.detail);
                break;
            }
          }
          finalize();
        } catch (cause) {
          if (cause instanceof DOMException && cause.name === "AbortError") {
            // 사용자가 정지를 누른 경우. 여기까지 받은 부분 답변은 남긴다.
            //  (에러로 인한 중단 시 부분 답변 유지 여부는 계약서 미정 — 위 TODO 참고.)
            finalize();
            return;
          }
          // 예상 못 한 예외. 규칙 7: 삼키지 않고 원인을 드러낸다.
          setError(
            cause instanceof Error
              ? cause.message
              : "채팅 응답을 처리하는 중 오류가 발생했습니다.",
          );
          setStreaming(null);
          setStatus(ChatStatus.Idle);
          abortRef.current = null;
        }
      };

      void run();
    },
    [status, turns],
  );

  return { turns, streaming, status, error, sendMessage, stopStreaming };
}
