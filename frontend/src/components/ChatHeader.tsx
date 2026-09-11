/**
 * 채팅 화면 상단 바.
 *
 * "성분 AI" 제목과 우측 "성분노트" 링크만 둔다. 시안의 "새 대화" 버튼과 시계(이력)
 * 아이콘은 이번 범위가 아니라 제외한다.
 */

export function ChatHeader() {
  return (
    <header className="flex shrink-0 items-center justify-between px-5 pb-3 pt-4">
      <h1 className="text-xl font-bold text-slate-900">성분 AI</h1>
      {/* TODO: 성분노트 화면이 생기면 라우트를 연결한다. 지금은 이동 대상이 없어 비활성. */}
      <button
        type="button"
        disabled
        className="text-sm font-medium text-slate-500"
      >
        성분노트
      </button>
    </header>
  );
}
