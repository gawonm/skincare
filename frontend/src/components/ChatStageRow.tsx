/**
 * 응답을 기다리는 동안 뜨는 진행 상태 행(시안 04C).
 *
 * 다이아몬드 아이콘 + 문구. 단일 JSON 응답에는 서버가 보내는 진행 문구가 없어서
 * 호출부가 고정 문구(`CHAT_PENDING_LABEL`)를 넘긴다.
 */

export function ChatStageRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-1 text-sm text-slate-500">
      {/* 45도 돌린 정사각형으로 다이아몬드(◇) 모양을 만든다. */}
      <span className="block size-3 rotate-45 rounded-[2px] border-2 border-accent-progress" />
      <span>{label}</span>
    </div>
  );
}
