/**
 * 상품 화면·API가 공유하는 상수.
 *
 * 규칙 9(매직 넘버·문자열 금지)에 따라 라우트/엔드포인트 경로와 분류값을 한곳에 모은다.
 *
 * 백엔드 API 경로(`/products`)와 프론트 상세페이지 라우트(`/product/:productId`)를
 * 일부러 다르게 둔다. 같으면 브라우저 내비게이션(GET, HTML)과 fetch(GET, JSON)를 vite
 * 프록시가 구분하지 못한다 — `/chat` 화면이 이미 겪은 문제와 같은 종류다(vite.config.ts 참고).
 */

/** 백엔드 `/products` 라우터의 경로. `vite.config.ts` 의 프록시 prefix와 맞물린다. */
export enum ProductEndpoint {
  Products = "/products",
}

/** 프론트 상품 상세페이지 라우트. `router.tsx` 가 이 패턴으로 등록한다. */
export enum ProductRoute {
  Detail = "/product/:productId",
}

export function buildProductDetailPath(productId: string): string {
  return `/product/${productId}`;
}

/** `models.product.ProductServiceCategory` 미러(값 문자열이 같아야 필터가 통한다). */
export enum ProductServiceCategory {
  EssenceSerum = "에센스·세럼",
  Ampoule = "앰플",
  CreamLotion = "크림·로션",
  TonerPad = "토너·패드",
  Cleanser = "클렌저",
  MaskPatch = "마스크·패치",
  Suncare = "선케어",
  Other = "기타",
}

/**
 * 홈 화면 2번째 줄(카테고리별 인기)의 후보 목록.
 * "기타"는 성격이 섞인 잡다한 묶음이라 카테고리 한 줄의 주제로 삼기 부적절해 뺀다.
 */
export const HOME_FEATURED_CATEGORY_CANDIDATES: readonly ProductServiceCategory[] = [
  ProductServiceCategory.EssenceSerum,
  ProductServiceCategory.Ampoule,
  ProductServiceCategory.CreamLotion,
  ProductServiceCategory.TonerPad,
  ProductServiceCategory.Cleanser,
  ProductServiceCategory.MaskPatch,
  ProductServiceCategory.Suncare,
];

/** 홈 화면 한 줄에 보여줄 기본 개수. 백엔드 기본값(4)과 맞춘다. */
export const HOME_SECTION_PRODUCT_LIMIT = 4;
