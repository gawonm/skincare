/**
 * 하단 탭 바 (홈 · AI 채팅 · MY). 시안 node 109:39 의 `Bottom Navigation`.
 *
 * 이번 범위에선 "AI 채팅" 만 활성이고 나머지는 표시만 한다. 다른 화면이 없으므로
 * 탭을 눌러도 라우팅하지 않는다(비활성 버튼).
 */

import { NAV_TAB_GLYPH, NAV_TABS, NavTabKey } from "../constants/chat";
import type { NavTabItem } from "../constants/chat";
import { UserIcon } from "./ChatIcons";

export function BottomTabBar() {
  return (
    <nav className="flex h-[72px] shrink-0 items-center justify-between border-t border-hairline bg-surface px-3 pb-3 pt-2">
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
        "flex h-12 flex-1 flex-col items-center justify-center gap-[3px] whitespace-nowrap",
        active ? "font-bold text-moss-deep" : "font-normal text-ink-soft",
      ].join(" ")}
    >
      {tab.key === NavTabKey.My ? (
        <UserIcon />
      ) : (
        <span aria-hidden="true" className="text-[17px] leading-none">
          {NAV_TAB_GLYPH[tab.key]}
        </span>
      )}
      <span className="text-[10px] leading-none">{tab.label}</span>
    </button>
  );
}
