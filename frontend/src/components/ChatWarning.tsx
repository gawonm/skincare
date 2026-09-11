/**
 * AI 답변에 딸리는 주의 문구(시안 04B 의 옅은 빨강 박스).
 *
 * TODO(contract): 경고를 별도 `warning` 이벤트로 받을지 `token` 본문에 섞을지 미정.
 *  지금은 별도 이벤트로 받은 문구 한 줄을 그린다.
 */

export function ChatWarning({ text }: { text: string }) {
  return (
    <div className="mt-2 flex items-start gap-1.5 rounded-xl bg-warn-surface px-3 py-2 text-xs text-warn-ink">
      <svg
        viewBox="0 0 24 24"
        className="mt-px size-4 shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 4 2 20h20L12 4z" />
        <path d="M12 10v5" />
        <path d="M12 18h.01" />
      </svg>
      <span>{text}</span>
    </div>
  );
}
