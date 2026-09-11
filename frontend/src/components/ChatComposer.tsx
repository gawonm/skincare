/**
 * 하단 입력창 + 전송/정지 버튼.
 *
 * - 최초 진입(대화 없음): 알약형 입력창 + 연회색 원형 전송 버튼(시안 04A).
 * - 대화 중: 사각형에 가까운 입력창 + 세이지 전송 버튼(시안 04B).
 * - 응답 중: placeholder 가 바뀌고 전송 버튼이 정지 버튼(사각형)으로 바뀐다(시안 04C).
 *
 * 입력값은 이 컴포넌트의 로컬 상태다. 제출 시에만 부모로 올려, 타이핑마다 화면
 * 전체가 리렌더되지 않게 한다.
 */

import { useState } from "react";
import type { FormEvent } from "react";

import { ChatPlaceholder, ChatStatus } from "../constants/chat";

interface ChatComposerProps {
  status: ChatStatus;
  /** 대화가 하나라도 시작됐는지(입력창 모양과 placeholder 를 가른다). */
  hasMessages: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
}

export function ChatComposer({ status, hasMessages, onSend, onStop }: ChatComposerProps) {
  const [value, setValue] = useState("");

  const streaming = status === ChatStatus.Streaming;
  // 대화 시작 전이면서 응답 중도 아닐 때만 알약형(시안 04A).
  const pill = !hasMessages && !streaming;
  const isEmpty = value.trim().length === 0;

  const placeholder = streaming
    ? ChatPlaceholder.Responding
    : hasMessages
      ? ChatPlaceholder.Conversation
      : ChatPlaceholder.Initial;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    // 응답 중에는 전송 자체가 정지 버튼으로 바뀌므로 여기 오지 않지만, 방어적으로 막는다.
    if (streaming || isEmpty) {
      return;
    }
    onSend(value);
    setValue("");
  };

  return (
    <form onSubmit={handleSubmit} className="flex shrink-0 items-center gap-2 px-4 pb-3 pt-2">
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        className={[
          "min-w-0 flex-1 border border-slate-200 px-4 py-3 text-sm outline-none transition",
          "placeholder:text-slate-400 focus:ring-2 focus:ring-sage-500",
          pill ? "rounded-full bg-slate-50" : "rounded-2xl bg-white",
        ].join(" ")}
      />

      {streaming ? (
        <button
          type="button"
          onClick={onStop}
          aria-label="응답 중지"
          className="grid size-11 shrink-0 place-items-center rounded-2xl bg-accent-stop text-white"
        >
          {/* 정지 = 채워진 사각형 */}
          <span className="block size-3 rounded-[3px] bg-white" />
        </button>
      ) : (
        <button
          type="submit"
          disabled={isEmpty}
          aria-label="전송"
          className={[
            "grid size-11 shrink-0 place-items-center transition",
            pill ? "rounded-full bg-slate-200 text-slate-500" : "rounded-2xl bg-sage-600 text-white hover:bg-sage-700",
            isEmpty ? "opacity-60" : "",
          ].join(" ")}
        >
          <svg
            viewBox="0 0 24 24"
            className="size-5"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M12 19V5" />
            <path d="m6 11 6-6 6 6" />
          </svg>
        </button>
      )}
    </form>
  );
}
