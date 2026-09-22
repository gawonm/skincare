/**
 * 로그인 사용자의 홈 화면 (Figma node 93:78).
 *
 * 홈 API 계약이 아직 없으므로, 화면 구조와 상호작용을 먼저 검증할 수 있도록
 * 시안의 상품·사용자 데이터를 여기서 고정한다. API 계약이 확정되면 이 데이터만
 * 서버 응답으로 교체한다.
 */

import { Component } from "react";

import { BottomTabBar } from "../components/BottomTabBar";
import { NavTabKey } from "../constants/chat";

enum HomeVisualSymbol {
  Serum = "◒",
  Cream = "◉",
}

class HomeProduct {
  public constructor(
    public readonly name: string,
    public readonly description: string,
    public readonly symbol: HomeVisualSymbol,
  ) {}
}

class HomeProductSection {
  public constructor(
    public readonly title: string,
    public readonly products: readonly HomeProduct[],
  ) {}
}

class HomeFixture {
  public static readonly userName = "서연";
  public static readonly skinTypeLabel = "지성 피부로 등록됨";
  public static readonly greeting = "오늘도 피부에 맞는 정보를 챙겨드릴게요";
  public static readonly recommendationTitle = "더 정확한 추천을 원하세요?";
  public static readonly recommendationDescription =
    "사용 중인 성분을 등록하면 궁합까지 확인해요.";
  public static readonly recommendationButton = "성분 등록하기";
  public static readonly sections: readonly HomeProductSection[] = [
    new HomeProductSection("지성 피부에 맞는 에센스", [
      new HomeProduct(
        "나이아신아마이드 세럼",
        "피지·모공 케어",
        HomeVisualSymbol.Serum,
      ),
      new HomeProduct(
        "티트리 밸런싱 에센스",
        "저자극 · 무향",
        HomeVisualSymbol.Serum,
      ),
    ]),
    new HomeProductSection("함께 보면 좋은 크림", [
      new HomeProduct(
        "히알루론 워터 크림",
        "산뜻한 마무리",
        HomeVisualSymbol.Cream,
      ),
      new HomeProduct("시카 진정 젤크림", "트러블 완화", HomeVisualSymbol.Cream),
    ]),
  ];
}

class ProductCard extends Component<{ product: HomeProduct }> {
  public render() {
    const { product } = this.props;

    return (
      <article className="flex h-[168px] w-[calc((100%-10px)/2)] flex-col gap-[7px] rounded-2xl border border-hairline bg-surface p-2.5">
        <div className="flex h-[82px] items-center justify-center rounded-[10px] bg-moss-tint text-[26px] text-ink">
          <span aria-hidden="true">{product.symbol}</span>
        </div>
        <h2 className="text-xs font-bold leading-[1.45] text-ink">{product.name}</h2>
        <p className="text-[10px] leading-[1.45] text-ink-soft">{product.description}</p>
      </article>
    );
  }
}

class ProductSection extends Component<{ section: HomeProductSection }> {
  public render() {
    const { section } = this.props;

    return (
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h1 className="text-[15px] font-bold leading-[1.45] text-ink">{section.title}</h1>
          <button type="button" disabled className="text-[11px] text-blue-point disabled:opacity-100">
            더보기
          </button>
        </div>
        <div className="flex gap-2.5">
          {section.products.map((product) => (
            <ProductCard key={product.name} product={product} />
          ))}
        </div>
      </section>
    );
  }
}

export class HomePage extends Component {
  public render() {
    return (
      <div className="mx-auto flex h-screen w-full max-w-md flex-col overflow-hidden bg-surface">
        <main className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-5 pb-4 pt-[54px]">
          <header className="flex flex-col gap-3">
            <div>
              <p className="text-[22px] font-bold leading-[1.45] text-ink">
                안녕하세요, {HomeFixture.userName}님
              </p>
              <p className="mt-1 text-[13px] leading-[1.45] text-ink-soft">
                {HomeFixture.greeting}
              </p>
            </div>
            <div className="flex w-fit items-center gap-[7px] rounded-full bg-moss-tint px-3 py-1.5">
              <span aria-hidden="true" className="size-1.5 rounded-full bg-moss-deep" />
              <span className="text-xs font-bold leading-[1.45] text-moss-deep">
                {HomeFixture.skinTypeLabel}
              </span>
            </div>
          </header>

          {HomeFixture.sections.map((section) => (
            <ProductSection key={section.title} section={section} />
          ))}

          <section className="flex flex-col gap-[5px] rounded-[18px] bg-moss-deep px-4 py-3.5 text-white">
            <h1 className="text-sm font-bold leading-[1.45]">{HomeFixture.recommendationTitle}</h1>
            <p className="text-[11px] leading-[1.45]">{HomeFixture.recommendationDescription}</p>
            <button
              type="button"
              disabled
              className="mt-0.5 w-fit rounded-[9px] bg-white px-3 py-2 text-[11px] font-bold leading-[1.45] text-moss-deep disabled:opacity-100"
            >
              {HomeFixture.recommendationButton}
            </button>
          </section>
        </main>

        <BottomTabBar activeTab={NavTabKey.Home} />
      </div>
    );
  }
}
