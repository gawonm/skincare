/**
 * AI 말풍선 안의 안전 안내(시안 109:76 `Safety Note`).
 *
 * `ChatTurnResponse.sections`의 `notice` 섹션(`unresolved` 문단이 구조화 데이터와 대조돼
 * 안내로 분류된 것, `docs/contracts/front-to-backend.md` "응답 확장: 섹션")을 여기에 연결한다
 * (`ChatMessageList`).
 */

export function ChatWarning({ text }: { text: string }) {
  return (
    <div className="rounded-[10px] bg-clay-tint px-2.5 py-2 text-[11px] leading-[1.45] font-medium text-clay">
      {`⚠ ${text}`}
    </div>
  );
}
