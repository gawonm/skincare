/**
 * 최초 진입 화면의 가운데 안내(시안 109:39).
 *
 * "SKINCARE ASSISTANT" 라벨 + 인사 heading + 보조 문구. 이름은 로그인 정보를 아직 안 불러와서
 * 이름 없는 폴백만 렌더한다.
 */

import { CHAT_EMPTY_STATE } from "../constants/chat";

export function ChatEmptyState() {
  return (
    // 시안에서 이 묶음의 중심이 헤더~입력창 사이 정중앙보다 약 49px 위라서, 아래 여백을 그
    // 두 배(98px)로 줘서 올린다. 고정 좌표 대신 이렇게 해야 화면 높이가 달라도 위치가 유지된다.
    <div className="flex h-full flex-col items-center justify-center pb-[98px] text-center">
      <p className="text-[11px] leading-[18px] font-bold text-moss-deep">
        {CHAT_EMPTY_STATE.eyebrow}
      </p>
      <h2 className="mt-3 text-[29px] leading-[41px] font-medium text-lavender-ink">
        {CHAT_EMPTY_STATE.greetingLine1}
        <br />
        {CHAT_EMPTY_STATE.greetingLine2}
      </h2>
      <p className="mt-3.5 text-[14px] leading-[22px] whitespace-pre-line text-ink-soft">
        {CHAT_EMPTY_STATE.subtext}
      </p>
    </div>
  );
}
