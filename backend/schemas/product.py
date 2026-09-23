"""`/products` 엔드포인트 요청/응답 모델.

`models.product.Product`를 그대로 내보내지 않는다. `local_image_path`(서버 내부 저장 경로),
`source`/`source_product_id`(수집 출처 식별자), `match_status`/`review_reasons`(검증 상태)는
화면에 노출할 이유가 없거나 노출하면 안 되는 내부 컬럼이다(규칙 17, docs/erd/app.md).

`image_url` 필드는 `Product.image_url`(올리브영 CDN 원본)을 그대로 옮긴다. data 파트 문서
(docs/data/README.md "상품 데이터를 다른 파트에 전달할 때")가 이미지는 파일로 전달하지 않고
이 CDN URL을 그대로 쓰라고 정해 뒀기 때문이다 — `local_image_path`는 수집 시점 로컬 경로라
이 서버 환경에는 없다. 그래서 이 모델들은 `from_attributes`로 자동 매핑하지 않고
`backend/services/product_query_service.py`가 필드별로 값을 채운다.
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
