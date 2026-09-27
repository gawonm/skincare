/**
 * AI 말풍선 안의 출처 줄(시안 109:76: "출처 · 성분 DB · 피부과 임상 가이드 2건").
 *
 * `ChatTurnResponse.sections`의 `evidence` 섹션이 담은 `references`(`ReferenceView`,
 * `docs/contracts/front-to-backend.md` "응답 확장: 섹션")를 `source_title` 기준으로 묶어
 * 이 모양으로 변환해 쓴다(`ChatMessageList`). 건수가 2 이상일 때만 "N건" 을 덧붙인다.
 */

interface SourceItem {
  label: string;
  count: number;
}

const SOURCE_PREFIX = "출처";
const SEPARATOR = " · ";
// 건수 표기를 붙이는 기준. 1건이면 라벨만, 2건 이상이면 "라벨 N건".
const COUNT_SUFFIX_THRESHOLD = 2;

function formatSourceItem(item: SourceItem): string {
  return item.count >= COUNT_SUFFIX_THRESHOLD ? `${item.label} ${item.count}건` : item.label;
}

export function ChatSources({ items }: { items: SourceItem[] }) {
  if (items.length === 0) {
    return null;
  }

  const line = [SOURCE_PREFIX, ...items.map(formatSourceItem)].join(SEPARATOR);

  return <p className="text-[10px] leading-[1.45] text-ink-soft">{line}</p>;
}
