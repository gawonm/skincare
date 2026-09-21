/**
 * 대화 메시지 목록(시안 04B) + 응답 대기 행(시안 04C) + 다시 시도 버튼.
 *
 * 새 메시지가 쌓이거나 대기 상태가 바뀔 때마다 맨 아래로 따라 내려간다.
 */

import { useEffect, useRef } from "react";

import { CHAT_PENDING_LABEL, CHAT_RETRY_LABEL } from "../constants/chat";
import type { ChatTurn } from "../hooks/useChat";
import { ChatBubble } from "./ChatBubble";
import { ChatStageRow } from "./ChatStageRow";

interface ChatMessageListProps {
  turns: ChatTurn[];
  /** 응답을 기다리는 중이면 진행 상태 행을 보여 준다. */
  waiting: boolean;
  /** 마지막 실패를 다시 보낼 수 있으면 목록 끝에 "다시 시도" 를 보여 준다. */
  canRetry: boolean;
  onRetry: () => void;
}

export function ChatMessageList({ turns, waiting, canRetry, onRetry }: ChatMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns, waiting, canRetry]);

  return (
    <div className="flex flex-col gap-4 px-4 py-4">
      {turns.map((turn, index) => (
        // 메시지는 append-only 이고 순서가 바뀌지 않으므로 index 를 key 로 써도 안전하다.
        // (재시도로 끝의 실패 안내를 걷어 낼 때도 뒤에서부터 지워서 앞 index 는 그대로다.)
        <ChatBubble key={index} role={turn.role} content={turn.content} tone={turn.tone} />
      ))}
      {waiting ? <ChatStageRow label={CHAT_PENDING_LABEL} /> : null}
      {canRetry && !waiting ? (
        <div className="flex justify-start">
          <button
            type="button"
            onClick={onRetry}
            className="rounded-full border border-sage-600 px-4 py-1.5 text-sm font-medium text-sage-700 transition hover:bg-sage-50"
          >
            {CHAT_RETRY_LABEL}
          </button>
        </div>
      ) : null}
      <div ref={endRef} />
    </div>
  );
}
