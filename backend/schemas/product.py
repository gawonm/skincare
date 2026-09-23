"""`/products` 엔드포인트 요청/응답 모델.

`models.product.Product`를 그대로 내보내지 않는다. `local_image_path`(서버 내부 저장 경로),
`source`/`source_product_id`(수집 출처 식별자), `match_status`/`review_reasons`(검증 상태)는
화면에 노출할 이유가 없거나 노출하면 안 되는 내부 컬럼이다(규칙 17, docs/erd/app.md).

`image_url` 필드는 `Product.image_url`(원본 쇼핑몰 CDN URL)을 그대로 옮기지 않는다.
`GET /products/{id}/image`를 가리키는 상대경로로 새로 만든다 — 그래서 이 모델들은
`from_attributes`로 자동 매핑하지 않고 `backend/services/product_query_service.py`가
필드별로 값을 채운다.

view_count: `models.product.Product`에 컬럼과 마이그레이션(`cdff29b164d8`)이 코드로는
준비돼 있지만, 로컬 DB에 마이그레이션을 아직 적용하지 않았다(2026-09-23, data 파트
확인 완료·적용 대기). 적용 전까지는 `ProductRepository`를 쓰는 모든 조회가 실패한다.
"""

from uuid import UUID

from pydantic import BaseModel

from models.product import ProductPriceBand, ProductServiceCategory


class ProductCardResponse(BaseModel):
    """홈 목록/카드용."""

    id: UUID
    display_title: str
    brand: str
    image_url: str
    lowest_price: int
    service_category: ProductServiceCategory | None
    volume_value: float | None
    volume_unit: str | None
    view_count: int


class ProductListResponse(BaseModel):
    items: list[ProductCardResponse]
    total: int


class ProductDetailResponse(BaseModel):
    """상세페이지용. 카드 필드 전부 + 구매/분류 정보(2026-09-23 사용자 확인)."""

    id: UUID
    display_title: str
    brand: str
    image_url: str
    lowest_price: int
    service_category: ProductServiceCategory | None
    volume_value: float | None
    volume_unit: str | None
    view_count: int
    maker: str | None
    category1: str
    category2: str | None
    category3: str | None
    price_band: ProductPriceBand
    shopping_url: str
    mall_name: str
