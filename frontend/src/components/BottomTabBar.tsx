/**
 * 하단 탭 바 (홈 · AI 채팅 · 스케줄 · 프로필).
 *
 * 이번 범위에선 "AI 채팅" 만 활성이고 나머지는 표시만 한다. 다른 화면이 없으므로
 * 탭을 눌러도 라우팅하지 않는다(비활성 버튼).
 */

import { NAV_TABS, NavTabKey } from "../constants/chat";
import type { NavTabItem } from "../constants/chat";

export function BottomTabBar() {
  return (
    <nav className="flex shrink-0 border-t border-slate-200 bg-white">
      {NAV_TABS.map((tab) => (
        <TabButton key={tab.key} tab={tab} />
      ))}
    </nav>
  );
}

function TabButton({ tab }: { tab: NavTabItem }) {
  const active = tab.enabled;

  return (
    <button
      type="button"
      disabled={!active}
      aria-current={active ? "page" : undefined}
      className={[
        "flex flex-1 flex-col items-center gap-1 py-2 text-xs",
        active ? "font-semibold text-sage-600" : "font-normal text-slate-400",
      ].join(" ")}
    >
      <TabIcon tabKey={tab.key} active={active} />
      <span>{tab.label}</span>
    </button>
  );
}

function TabIcon({ tabKey, active }: { tabKey: NavTabKey; active: boolean }) {
  const common = {
    viewBox: "0 0 24 24",
    className: "size-5",
    "aria-hidden": true,
  } as const;

  switch (tabKey) {
    case NavTabKey.Home:
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 10.5 12 3l9 7.5" />
          <path d="M5 9.5V21h14V9.5" />
        </svg>
      );
    case NavTabKey.Chat:
      // 활성 탭은 채워진 4각 별(시안), 비활성은 외곽선만.
      return (
        <svg
          {...common}
          fill={active ? "currentColor" : "none"}
          stroke="currentColor"
          strokeWidth={2}
          strokeLinejoin="round"
        >
          <path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z" />
        </svg>
      );
    case NavTabKey.Schedule:
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 4h14v16H5z" />
          <path d="M8 9h8" />
          <path d="M8 13h8" />
          <path d="M8 17h5" />
        </svg>
      );
    case NavTabKey.Profile:
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth={2}>
          <circle cx="12" cy="12" r="8.5" />
        </svg>
      );
  }
}
