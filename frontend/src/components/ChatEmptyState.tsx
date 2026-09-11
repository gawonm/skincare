/**
 * 04A 최초 진입 화면의 가운데 안내.
 *
 * "SKINCARE ASSISTANT" 라벨 + 인사 heading + 회색 서브텍스트.
 * 이름은 로그인 시에만 있으므로 지금은 이름 없는 폴백만 렌더한다.
 * (TODO: useAuth 연결 후 로그인 사용자에겐 "안녕하세요 {name}님".)
 */

import { CHAT_EMPTY_STATE } from "../constants/chat";

export function ChatEmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <p className="text-sm font-bold tracking-[0.15em] text-brand-ink">
        {CHAT_EMPTY_STATE.eyebrow}
      </p>
      <h2 className="mt-6 text-2xl font-bold leading-snug text-brand-ink">
        {CHAT_EMPTY_STATE.greetingLine1}
        <br />
        {CHAT_EMPTY_STATE.greetingLine2}
      </h2>
      <p className="mt-4 whitespace-pre-line text-sm leading-relaxed text-slate-400">
        {CHAT_EMPTY_STATE.subtext}
      </p>
    </div>
  );
}
