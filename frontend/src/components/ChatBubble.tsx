/**
 * 말풍선 한 개(시안 109:76).
 *
 * 사용자 말풍선은 오른쪽(이끼색), AI 말풍선은 왼쪽(연회색)이다. 오류 안내는 AI 쪽 말풍선을
 * 안전 안내와 같은 clay 색으로 그린다. AI 말풍선 안에 딸리는 안전 안내·출처 줄, 그리고
 * 응답 섹션(`ChatMessageList`가 `sections`로 그리는 블록들)은 `children` 으로 받아 본문
 * 아래에 세로로 쌓는다.
 *
 * `content`가 `null`이면 고정 문단을 그리지 않는다 — 섹션 기반 렌더링처럼 본문 전체를
 * `children`이 대신할 때, 빈 문단이 위에 얹혀 불필요한 여백이 생기지 않게 하기 위해서다.
 */

import type { ReactNode } from "react";

import { ChatRole, ChatTurnTone } from "../constants/chat";

interface ChatBubbleProps {
  role: ChatRole;
  content?: string | null;
  tone?: ChatTurnTone;
  children?: ReactNode;
}

export function ChatBubble({
  role,
  content = null,
  tone = ChatTurnTone.Normal,
  children,
}: ChatBubbleProps) {
  const isUser = role === ChatRole.User;
  const isError = tone === ChatTurnTone.Error;

  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        role={isError ? "alert" : undefined}
        className={[
          // 시안의 말풍선 최대 폭이 294px 이다. 짧은 말은 내용 폭에 맞춰 줄어든다.
          "flex max-w-[294px] flex-col gap-2 rounded-2xl px-[13px] py-2.5 text-[13px] leading-[1.45] whitespace-pre-wrap",
          isUser
            ? "bg-moss text-white"
            : isError
              ? "bg-clay-tint text-clay"
              : "bg-surface-2 text-ink",
        ].join(" ")}
      >
        {content !== null ? <p>{content}</p> : null}
        {children}
      </div>
    </div>
  );
}
