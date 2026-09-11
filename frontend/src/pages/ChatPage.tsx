/**
 * AI 채팅 화면 (시안 04A 최초 진입 / 04B 대화 중 / 04C 응답 중).
 *
 * 지금은 목 스트림만 쓴다. 실제 백엔드 연동은 `api/chatMock.ts` → `api/chat.ts`
 * 교체로 끝나도록, 데이터 접근은 전부 `useChat` 훅 뒤에 있다.
 */

import { useEffect } from "react";

import { BottomTabBar } from "../components/BottomTabBar";
import { ChatComposer } from "../components/ChatComposer";
import { ChatEmptyState } from "../components/ChatEmptyState";
import { ChatHeader } from "../components/ChatHeader";
import { ChatMessageList } from "../components/ChatMessageList";
import { FormAlert } from "../components/FormAlert";
import { useChat } from "../hooks/useChat";

export function ChatPage() {
  const { turns, streaming, status, error, sendMessage, stopStreaming } = useChat();
  const hasMessages = turns.length > 0 || streaming !== null;

  // 화면을 벗어나면 진행 중인 목 스트림을 정리한다(계약서: 화면 이탈 = 초기화).
  useEffect(() => stopStreaming, [stopStreaming]);

  return (
    <div className="mx-auto flex h-screen w-full max-w-md flex-col bg-canvas">
      <ChatHeader />

      <main className="min-h-0 flex-1 overflow-y-auto">
        {hasMessages ? (
          <ChatMessageList turns={turns} streaming={streaming} />
        ) : (
          <ChatEmptyState />
        )}
      </main>

      {error !== null ? (
        <div className="px-4 pb-2">
          {/* TODO(contract): 에러 시 재시도 버튼·부분 답변 처리 방식은 미정. 지금은 문구만. */}
          <FormAlert tone="error" message={error} />
        </div>
      ) : null}

      <ChatComposer
        status={status}
        hasMessages={hasMessages}
        onSend={sendMessage}
        onStop={stopStreaming}
      />

      <BottomTabBar />
    </div>
  );
}
