/**
 * `/products` 요청 함수와 그 입출력 타입.
 *
 * 타입은 `backend/schemas/product.py` 와 1:1 로 맞춘다. 백엔드가 필드를 바꾸면 여기도
 * 같이 바꿔야 하며, 그 전까지는 컴파일이 통과해도 런타임에서 어긋난다(`auth.ts` 와 같은 패턴).
 *
 * `view_count`: 백엔드 코드·마이그레이션은 준비됐지만 로컬 DB에 아직 적용 전이다
 * (2026-09-23, docs/erd/app.md "조회수 카운터 확장안"). 적용 전까지는 `/products*` 호출이
 * 전부 실패한다.
 */

import type { ProductServiceCategory } from "../constants/product";
import { ProductEndpoint } from "../constants/product";
import { fetchJson } from "./client";

/** 홈 목록/카드용(`ProductCardResponse`). */
export interface ProductCard {
  id: string;
  display_title: string;
  brand: string;
  image_url: string;
  lowest_price: number;
  service_category: ProductServiceCategory | null;
  volume_value: number | null;
  volume_unit: string | null;
  view_count: number;
}

/** `ProductListResponse`. */
export interface ProductListResponse {
  items: ProductCard[];
  total: number;
}

/** 상세페이지용(`ProductDetailResponse`). 카드 필드 전부 + 구매/분류 정보. */
export interface ProductDetail extends ProductCard {
  maker: string | null;
  category1: string;
  category2: string | null;
  category3: string | null;
  price_band: string;
  shopping_url: string;
  mall_name: string;
}

export interface ListPopularParams {
  serviceCategory?: ProductServiceCategory;
  limit?: number;
}

export class ProductApi {
  /** 인기 상품 목록. `serviceCategory` 를 생략하면 전체 인기순이다. */
  static listPopular(params: ListPopularParams = {}): Promise<ProductListResponse> {
    const query = new URLSearchParams();
    if (params.serviceCategory !== undefined) {
      query.set("service_category", params.serviceCategory);
    }
    if (params.limit !== undefined) {
      query.set("limit", String(params.limit));
    }
    const suffix = query.toString();
    const path = suffix.length > 0 ? `${ProductEndpoint.Products}?${suffix}` : ProductEndpoint.Products;
    return fetchJson<ProductListResponse>(path);
  }

  static getDetail(productId: string): Promise<ProductDetail> {
    return fetchJson<ProductDetail>(`${ProductEndpoint.Products}/${productId}`);
  }
}
