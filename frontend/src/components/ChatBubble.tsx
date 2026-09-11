/**
 * 말풍선 한 개.
 *
 * 사용자 말풍선은 오른쪽(세이지), AI 말풍선은 왼쪽(연회색). AI 말풍선에 딸리는
 * 경고 박스는 `children` 으로 받아 본문 아래에 넣는다(출처 줄은 말풍선 밖이라 여기서 안 받는다).
 */

import type { ReactNode } from "react";

import { ChatRole } from "../constants/chat";

interface ChatBubbleProps {
  role: ChatRole;
  content: string;
  children?: ReactNode;
}

export function ChatBubble({ role, content, children }: ChatBubbleProps) {
  const isUser = role === ChatRole.User;

  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={[
          "max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap",
          isUser ? "bg-sage-600 text-white" : "bg-ai-surface text-ai-ink",
        ].join(" ")}
      >
        <p>{content}</p>
        {children}
      </div>
    </div>
  );
}
