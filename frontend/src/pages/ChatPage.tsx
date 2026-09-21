/**
 * AI 채팅 화면 (시안 04A 최초 진입 / 04B 대화 중 / 04C 응답 중).
 *
 * `POST /chat` 은 로그인 사용자 전용이라 세션이 없으면 훅이 로그인 화면으로 보낸다.
 * 데이터 접근은 전부 `useChat` 훅 뒤에 있다.
 */

import { useEffect } from "react";

import { BottomTabBar } from "../components/BottomTabBar";
import { ChatComposer } from "../components/ChatComposer";
import { ChatEmptyState } from "../components/ChatEmptyState";
import { ChatHeader } from "../components/ChatHeader";
import { ChatMessageList } from "../components/ChatMessageList";
import { ChatStatus } from "../constants/chat";
import { useChat } from "../hooks/useChat";

export function ChatPage() {
  const { turns, status, canRetry, sendMessage, retry, stopSending } = useChat();
  const sending = status === ChatStatus.Sending;
  const hasMessages = turns.length > 0;

  // 화면을 벗어나면 진행 중인 요청 대기를 끊는다. 서버는 그 턴을 계속 처리하고,
  // 다시 들어오면 화면은 비어 있어도 Agent 는 기억한다(계약서 "범위").
  useEffect(() => stopSending, [stopSending]);

  return (
    <div className="mx-auto flex h-screen w-full max-w-md flex-col bg-canvas">
      <ChatHeader />

      <main className="min-h-0 flex-1 overflow-y-auto">
        {hasMessages ? (
          <ChatMessageList
            turns={turns}
            waiting={sending}
            canRetry={canRetry}
            onRetry={retry}
          />
        ) : (
          <ChatEmptyState />
        )}
      </main>

      <ChatComposer
        status={status}
        hasMessages={hasMessages}
        onSend={sendMessage}
        onStop={stopSending}
      />

      <BottomTabBar />
    </div>
  );
}
