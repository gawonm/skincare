/**
 * 응답을 기다리는 동안 뜨는 진행 상태 행(시안 109:118).
 *
 * 점 세 개 + 문구. 단일 JSON 응답에는 서버가 보내는 진행 문구가 없어서
 * 호출부가 고정 문구(`CHAT_PENDING_LABEL`)를 넘긴다.
 */

import { LoadingDotsIcon } from "./ChatIcons";

export function ChatStageRow({ label }: { label: string }) {
  return (
    <div role="status" className="flex h-[68px] items-center gap-3">
      <LoadingDotsIcon />
      <span className="text-[15px] font-medium whitespace-nowrap text-ink-soft">{label}</span>
    </div>
  );
}
