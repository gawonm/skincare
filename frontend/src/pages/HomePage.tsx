/**
 * 로그인 사용자의 홈 화면 (Figma node 93:78).
 *
 * 상품 목록은 `GET /products`(useHomeProducts)로 실제 데이터를 받는다. 인사말·피부 타입·
 * 추천 CTA는 로그인 개인화 홈이 아직 범위 밖이라(2026-09-17 확정) 계속 고정값을 쓴다
 * — API 계약이 생기면 이 부분만 교체한다.
 */

import { Component } from "react";
import { Link } from "react-router-dom";

import { BottomTabBar } from "../components/BottomTabBar";
import { NavTabKey } from "../constants/chat";
import { buildProductDetailPath } from "../constants/product";
import { useHomeProducts } from "../hooks/useHomeProducts";
import type { ProductCard as ProductCardData } from "../api/product";

class HomeFixture {
  public static readonly userName = "서연";
  public static readonly skinTypeLabel = "지성 피부로 등록됨";
  public static readonly greeting = "오늘도 피부에 맞는 정보를 챙겨드릴게요";
  public static readonly recommendationTitle = "더 정확한 추천을 원하세요?";
  public static readonly recommendationDescription =
    "사용 중인 성분을 등록하면 궁합까지 확인해요.";
  public static readonly recommendationButton = "성분 등록하기";
}

function formatPrice(won: number): string {
  return `${won.toLocaleString("ko-KR")}원`;
}

class ProductCard extends Component<{ product: ProductCardData }> {
  public render() {
    const { product } = this.props;

    return (
      <Link
        to={buildProductDetailPath(product.id)}
        className="flex h-[168px] w-[calc((100%-10px)/2)] flex-col gap-[7px] rounded-2xl border border-hairline bg-surface p-2.5"
      >
        <div className="flex h-[82px] items-center justify-center overflow-hidden rounded-[10px] bg-moss-tint">
          <img src={product.image_url} alt={product.display_title} className="size-full object-cover" />
        </div>
        <h2 className="truncate text-xs font-bold leading-[1.45] text-ink">
          {product.display_title}
        </h2>
        <p className="text-[10px] leading-[1.45] text-ink-soft">
          {product.brand} · {formatPrice(product.lowest_price)}
        </p>
      </Link>
    );
  }
}

class ProductSection extends Component<{ title: string; products: readonly ProductCardData[] }> {
  public render() {
    const { title, products } = this.props;

    if (products.length === 0) {
      return null;
    }

    return (
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h1 className="text-[15px] font-bold leading-[1.45] text-ink">{title}</h1>
          <button type="button" disabled className="text-[11px] text-blue-point disabled:opacity-100">
            더보기
          </button>
        </div>
        <div className="flex gap-2.5">
          {products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      </section>
    );
  }
}

export function HomePage() {
  const { overall, featured, featuredCategory, isLoading, isError } = useHomeProducts();

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

        {isLoading ? <p className="py-6 text-center text-[13px] text-ink-soft">불러오는 중...</p> : null}
        {isError ? (
          <p className="py-6 text-center text-[13px] text-clay">
            상품을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </p>
        ) : null}

        <ProductSection title="지금 가장 인기 있는 상품" products={overall} />
        <ProductSection title={`지금 인기 있는 ${featuredCategory}`} products={featured} />

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
