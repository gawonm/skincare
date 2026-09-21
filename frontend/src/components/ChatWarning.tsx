/**
 * AI 말풍선 안의 안전 안내(시안 109:76 `Safety Note`).
 *
 * TODO(design): 응답 어느 필드(`unresolved`, `partial` 상태 등)를 여기에 보여 줄지 정해지지
 *  않아 아직 어디서도 쓰지 않는다. 지금은 시안 모양만 맞춰 둔다.
 */

export function ChatWarning({ text }: { text: string }) {
  return (
    <div className="rounded-[10px] bg-clay-tint px-2.5 py-2 text-[11px] leading-[1.45] font-medium text-clay">
      {`⚠ ${text}`}
    </div>
  );
}
