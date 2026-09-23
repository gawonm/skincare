/**
 * 상품 상세페이지. 홈 카드 클릭과 채팅 제품 링크가 모두 여기로 온다(`product_id` 하나로).
 *
 * 담는 정보 범위는 2026-09-23 확정: 카드 필드(이름/브랜드/이미지/가격) + 제조사/분류/용량/
 * 가격대/구매 링크/판매처명. 채팅 추천 근거는 상세페이지 소유가 아니라(상품 하나가 아니라
 * 추천 턴마다 달라지는 값) 넣지 않는다.
 */

import { useNavigate, useParams } from "react-router-dom";

import { useProductDetail } from "../hooks/useProductDetail";

function formatPrice(won: number): string {
  return `${won.toLocaleString("ko-KR")}원`;
}

function formatVolume(value: number | null, unit: string | null): string | null {
  if (value === null || unit === null) {
    return null;
  }
  return `${value}${unit}`;
}

export function ProductDetailPage() {
  const { productId } = useParams<{ productId: string }>();
  const navigate = useNavigate();
  const { data: product, isLoading, isError, error } = useProductDetail(productId);

  return (
    <div className="mx-auto flex h-screen w-full max-w-md flex-col overflow-y-auto bg-surface">
      <header className="flex h-[52px] shrink-0 items-center px-5">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="text-[13px] font-bold text-moss-deep"
        >
          ‹ 뒤로
        </button>
      </header>

      <main className="flex flex-1 flex-col gap-4 px-5 pb-8">
        {isLoading ? (
          <p className="pt-10 text-center text-[13px] text-ink-soft">불러오는 중...</p>
        ) : null}

        {isError ? (
          <p className="pt-10 text-center text-[13px] text-clay">
            {error instanceof Error ? error.message : "상품 정보를 불러오지 못했습니다."}
          </p>
        ) : null}

        {product ? (
          <>
            <div className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-2xl bg-surface-2">
              <img
                src={product.image_url}
                alt={product.display_title}
                className="size-full object-cover"
              />
            </div>

            <div className="flex flex-col gap-1">
              <p className="text-[13px] font-bold text-moss-deep">{product.brand}</p>
              <h1 className="text-lg font-bold leading-[1.45] text-ink">
                {product.display_title}
              </h1>
              <p className="text-base font-bold text-ink">{formatPrice(product.lowest_price)}</p>
              <p className="text-[11px] text-ink-soft">
                {product.view_count.toLocaleString("ko-KR")}명이 봤어요
              </p>
            </div>

            <dl className="flex flex-col gap-2 rounded-2xl border border-hairline p-4 text-[13px]">
              {product.maker !== null ? (
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-soft">제조사</dt>
                  <dd className="text-ink">{product.maker}</dd>
                </div>
              ) : null}
              <div className="flex justify-between gap-3">
                <dt className="text-ink-soft">분류</dt>
                <dd className="text-ink">
                  {[product.category1, product.category2, product.category3]
                    .filter((value): value is string => value !== null)
                    .join(" · ")}
                </dd>
              </div>
              {formatVolume(product.volume_value, product.volume_unit) !== null ? (
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-soft">용량</dt>
                  <dd className="text-ink">
                    {formatVolume(product.volume_value, product.volume_unit)}
                  </dd>
                </div>
              ) : null}
              <div className="flex justify-between gap-3">
                <dt className="text-ink-soft">판매처</dt>
                <dd className="text-ink">{product.mall_name}</dd>
              </div>
            </dl>

            <a
              href={product.shopping_url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 flex items-center justify-center rounded-[9px] bg-moss-deep px-3 py-3 text-[13px] font-bold text-white"
            >
              {product.mall_name}에서 구매하기
            </a>
          </>
        ) : null}
      </main>
    </div>
  );
}
