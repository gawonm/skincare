/**
 * 로그인·회원가입 두 화면이 공유하는 껍데기.
 *
 * 화면 중앙에 카드 하나를 놓고 제목/부제와 본문(폼) 슬롯을 제공한다. 레이아웃을
 * 여기 모아 두 페이지가 여백·정렬을 각자 다르게 잡는 일을 막는다.
 */

import type { ReactNode } from "react";

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  children: ReactNode;
  /** 카드 하단의 보조 링크 영역(예: "회원가입으로 이동"). */
  footer: ReactNode;
}

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <header className="mb-5">
          <h1 className="text-lg font-bold text-slate-900">{title}</h1>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
        </header>
        {children}
        <footer className="mt-5 text-center text-sm text-slate-500">{footer}</footer>
      </div>
    </div>
  );
}
