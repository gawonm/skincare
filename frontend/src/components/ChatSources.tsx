/**
 * AI 답변 아래 붙는 출처 줄(시안 04B: "출처 · 성분 DB · 피부과 임상 가이드 2건").
 *
 * TODO(contract): sources 객체 형태가 미정이다. 지금은 라벨과 건수만 온다고 보고,
 *  건수가 2 이상일 때만 "N건" 을 덧붙인다. 링크/id 가 필요해지면 여기와 스키마를 함께 고친다.
 */

import type { SourceItem } from "../schemas/chat";

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

  return <p className="px-1 pt-1 text-xs text-slate-400">{line}</p>;
}
