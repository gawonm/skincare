/**
 * 채팅 화면 시안(피그마 109:39 / 109:118)에서 내려받은 아이콘 3종.
 *
 * SVG 원본의 path·색·크기를 그대로 옮겼다. 색이 시안에 고정돼 있어서(`stroke`, `fill`)
 * 부모의 `color` 로 바뀌지 않는다.
 */

/** 전송 화살표(`icon/send`, 18×18). */
export function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path
        d="M9 14.25V3.75M12.75 7.5L9 3.75L5.25 7.5"
        stroke="#7B8A80"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** 하단 탭 "MY" 사용자 아이콘(`user`, 20×20). */
export function UserIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M15.834 17.5V15.8333C15.834 14.9493 15.4828 14.1014 14.8576 13.4763C14.2324 12.8512 13.3844 12.5 12.5003 12.5H7.49971C6.61556 12.5 5.76761 12.8512 5.14242 13.4763C4.51723 14.1014 4.166 14.9493 4.166 15.8333V17.5M13.3337 5.83333C13.3337 7.67428 11.8412 9.16667 10 9.16667C8.15884 9.16667 6.66629 7.67428 6.66629 5.83333C6.66629 3.99238 8.15884 2.5 10 2.5C11.8412 2.5 13.3337 3.99238 13.3337 5.83333Z"
        stroke="#5B6A5E"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** 응답 대기 점 세 개(`Loading Dots`, 30×6). */
export function LoadingDotsIcon() {
  return (
    <svg width="30" height="6" viewBox="0 0 30 6" fill="none" aria-hidden="true">
      <circle cx="3" cy="3" r="3" fill="#65E0E5" />
      <circle cx="15" cy="3" r="3" fill="#2B7FFF" />
      <circle cx="27" cy="3" r="3" fill="#7C66F2" />
    </svg>
  );
}
