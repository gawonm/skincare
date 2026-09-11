/**
 * 응답 중, 아직 본문 토큰이 안 온 구간에 뜨는 진행 상태 행(시안 04C).
 *
 * 다이아몬드 아이콘 + 문구. 문구는 계약서 `stage` 이벤트의 label 을 그대로 쓴다.
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
