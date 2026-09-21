/**
 * 하단 입력창 + 전송/정지 버튼(시안 109:39 / 109:76 / 109:118).
 *
 * - 평상시: 흰 알약 입력창 + 연회색 원형 전송 버튼.
 * - 응답 대기 중: placeholder 가 비고 전송 버튼이 검은 정지 버튼으로 바뀐다.
 * - 최초 진입은 테두리 전체, 대화 중은 위쪽 테두리만 있다(시안 그대로).
 *
 * 입력값은 이 컴포넌트의 로컬 상태다. 제출 시에만 부모로 올려, 타이핑마다 화면
 * 전체가 리렌더되지 않게 한다.
 */

import { useState } from "react";
import type { FormEvent } from "react";

import { CHAT_INPUT_PLACEHOLDER, ChatStatus } from "../constants/chat";
import { SendIcon } from "./ChatIcons";

interface ChatComposerProps {
  status: ChatStatus;
  /** 대화가 하나라도 시작됐는지(테두리 모양을 가른다). */
  hasMessages: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
}

export function ChatComposer({ status, hasMessages, onSend, onStop }: ChatComposerProps) {
  const [value, setValue] = useState("");

  const sending = status === ChatStatus.Sending;
  const isEmpty = value.trim().length === 0;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    // 응답 대기 중에는 전송 버튼이 정지 버튼으로 바뀌므로 여기 오지 않지만, Enter 로 오는
    // 경우를 막기 위해 방어적으로 거른다.
    if (sending || isEmpty) {
      return;
    }
    onSend(value);
    setValue("");
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={[
        "flex h-[52px] shrink-0 items-center justify-between rounded-[26px] border-hairline bg-white pr-2 pl-[18px]",
        "shadow-[0_5px_14px_rgba(64,82,71,0.1)] focus-within:ring-2 focus-within:ring-moss/40",
        hasMessages ? "border-t" : "border",
      ].join(" ")}
    >
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={sending ? "" : CHAT_INPUT_PLACEHOLDER}
        aria-label={CHAT_INPUT_PLACEHOLDER}
        className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-soft"
      />

      {sending ? (
        <button
          type="button"
          onClick={onStop}
          aria-label="응답 중지"
          className="grid size-10 shrink-0 place-items-center rounded-[20px] bg-stop-surface"
        >
          {/* 정지 = 흰 사각형 */}
          <span className="block size-2.5 rounded-[2px] bg-white" />
        </button>
      ) : (
        <button
          type="submit"
          disabled={isEmpty}
          aria-label="전송"
          className="grid size-10 shrink-0 place-items-center rounded-[20px] bg-surface-2"
        >
          <SendIcon />
        </button>
      )}
    </form>
  );
}
