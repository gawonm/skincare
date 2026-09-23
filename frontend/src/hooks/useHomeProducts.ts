/**
 * 홈 화면 인기 상품 두 줄을 가져오는 훅.
 *
 * 1번째 줄은 전체 인기순(카테고리 필터 없음), 2번째 줄은 카테고리 하나를 날짜 시드
 * 결정적 랜덤으로 골라 그 안에서 인기순이다(2026-09-23 확정, `docs/erd/app.md` 대신
 * 여기서는 백엔드를 거치지 않는다 — `GET /products`가 순수 목록 조회 API라서, "오늘의
 * 카테고리" 선택 자체는 프론트가 계산하고 그 값으로 같은 API를 한 번 더 부른다).
 *
 * 날짜 시드는 하루 동안 같은 값을 내고 전체 사용자가 같은 결과를 보게 한다. 저장소가
 * 따로 필요 없다 — 매 렌더마다 같은 날짜면 같은 카테고리가 계산된다.
 */

import { useQuery } from "@tanstack/react-query";

import type { ProductCard } from "../api/product";
import { ProductApi } from "../api/product";
import type { ProductServiceCategory } from "../constants/product";
import { HOME_FEATURED_CATEGORY_CANDIDATES, HOME_SECTION_PRODUCT_LIMIT } from "../constants/product";

/** 문자열 시드로 후보 목록에서 하나를 결정적으로 고른다. */
class DailyPicker {
  private static hash(seed: string): number {
    let hash = 0;
    for (let index = 0; index < seed.length; index += 1) {
      hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
    }
    return hash;
  }

  public static pick<T>(candidates: readonly T[], seed: string): T {
    const index = this.hash(seed) % candidates.length;
    return candidates[index];
  }
}

function todaySeed(): string {
  // UTC 기준 날짜 문자열(YYYY-MM-DD). 서버 없이 프론트에서만 계산하므로 로컬 표준시가
  // 아니라 UTC로 고정해야 여러 브라우저에서 같은 날 같은 값이 나온다.
  return new Date().toISOString().slice(0, 10);
}

export function pickFeaturedCategory(): ProductServiceCategory {
  return DailyPicker.pick(HOME_FEATURED_CATEGORY_CANDIDATES, todaySeed());
}

export interface HomeProductsResult {
  overall: ProductCard[];
  featuredCategory: ProductServiceCategory;
  featured: ProductCard[];
  isLoading: boolean;
  isError: boolean;
}

export function useHomeProducts(): HomeProductsResult {
  const featuredCategory = pickFeaturedCategory();

  const overallQuery = useQuery({
    queryKey: ["products", "popular", "overall"],
    queryFn: () => ProductApi.listPopular({ limit: HOME_SECTION_PRODUCT_LIMIT }),
  });
  const featuredQuery = useQuery({
    queryKey: ["products", "popular", featuredCategory],
    queryFn: () =>
      ProductApi.listPopular({ serviceCategory: featuredCategory, limit: HOME_SECTION_PRODUCT_LIMIT }),
  });

  return {
    overall: overallQuery.data?.items ?? [],
    featuredCategory,
    featured: featuredQuery.data?.items ?? [],
    isLoading: overallQuery.isLoading || featuredQuery.isLoading,
    isError: overallQuery.isError || featuredQuery.isError,
  };
}
