/**
 * 로그인·회원가입 화면이 공유하는 뼈대(피그마 node 93:2, 93:25).
 *
 * 채팅 화면(`ChatPage`)과 같은 모바일 폭(`max-w-md`) 페이지로 취급한다. 피그마 시안의
 * 기기 상태 표시줄("9:41" 등)은 목업용 기기 프레임이라 실제 화면에는 넣지 않는다
 * (사용자 확인 완료). 화면마다 배지·제목·본문 구성이 달라 제목/부제 props 로 묶지
 * 않고, 배경·여백만 제공한다.
 */

import type { ReactNode } from "react";

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col bg-surface px-5 pt-9 pb-6">
      {children}
    </div>
  );
}
