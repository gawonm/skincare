/**
 * 채팅 화면 상단. 시안(109:39 / 109:76)에는 제목 없이 우측 "새 대화" 만 있다.
 *
 * "새 대화" 는 대화 초기화 엔드포인트가 미정이라(계약서 "아직 안 정한 것" 2번) 시안대로
 * 그리기만 하고 동작하지 않는다. 결정되면 `onClick` 을 연결하고 `disabled` 를 푼다.
 */

import { CHAT_NEW_CONVERSATION_LABEL } from "../constants/chat";

export function ChatHeader() {
  return (
    <header className="mt-2.5 flex h-[52px] shrink-0 items-center justify-end">
      <button
        type="button"
        disabled
        className="text-[13px] font-bold whitespace-nowrap text-moss-deep"
      >
        {CHAT_NEW_CONVERSATION_LABEL}
      </button>
    </header>
  );
}
