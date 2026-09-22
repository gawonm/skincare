/**
 * 하단 탭 바 (홈 · AI 채팅 · MY). 시안 node 109:39 의 `Bottom Navigation`.
 *
 * 홈과 AI 채팅은 공통 컴포넌트에서 라우팅한다. MY는 프로필 화면과 계약이 아직 없어서
 * 시안대로 보이되 비활성 상태를 유지한다.
 */

import { Component } from "react";
import { Link } from "react-router-dom";

import {
  NAV_TAB_GLYPH,
  NAV_TAB_ROUTE,
  NAV_TABS,
  NavTabAvailability,
  NavTabItem,
  NavTabKey,
} from "../constants/chat";
import { UserIcon } from "./ChatIcons";

export class BottomTabBar extends Component<{ activeTab: NavTabKey }> {
  public render() {
    const { activeTab } = this.props;

    return (
      <nav className="flex h-[72px] shrink-0 items-center justify-between border-t border-hairline bg-surface px-3 pb-3 pt-2">
        {NAV_TABS.map((tab) => (
          <TabButton key={tab.key} tab={tab} activeTab={activeTab} />
        ))}
      </nav>
    );
  }
}

class TabButton extends Component<{ tab: NavTabItem; activeTab: NavTabKey }> {
  public render() {
    const { activeTab, tab } = this.props;
    const active = tab.key === activeTab;
    const route = NAV_TAB_ROUTE[tab.key];
    const className = [
      "flex h-12 flex-1 flex-col items-center justify-center gap-[3px] whitespace-nowrap",
      active ? "font-bold text-moss-deep" : "font-normal text-ink-soft",
    ].join(" ");

    if (tab.availability === NavTabAvailability.Disabled || route === null) {
      return (
        <button type="button" disabled className={`${className} disabled:opacity-100`}>
          <UserIcon />
          <span className="text-[10px] leading-none">{tab.label}</span>
        </button>
      );
    }

    return (
      <Link to={route} aria-current={active ? "page" : undefined} className={className}>
        <span aria-hidden="true" className="text-[17px] leading-none">
          {NAV_TAB_GLYPH[tab.key]}
        </span>
        <span className="text-[10px] leading-none">{tab.label}</span>
      </Link>
    );
  }
}
