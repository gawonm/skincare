"""네이버 쇼핑 후보 수집 단계가 주고받는 Enum 과 Pydantic 모델.

단계 간에 dict 나 튜플을 그대로 넘기지 않는다.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TargetGroup(StrEnum):
    """MVP 성분군 화이트리스트 단위. `docs/data/data.md` 의 성분 범위 표와 일치시킨다."""

    VITAMIN_C = "Vitamin C"
    NIACINAMIDE = "Niacinamide"
    RETINOL = "Retinol"
    AHA = "AHA"
    BHA = "BHA"


class PriceBand(StrEnum):
    """`lowest_price` 기준 가격대. 경계값은 `PriceBandClassifier` 에서 관리한다."""

    UNDER_10K = "1만원 미만"
    BAND_10K = "1만원대"
    BAND_20K = "2만원대"
    BAND_30K_40K = "3~4만원대"
    OVER_50K = "5만원 이상"


class MatchStatus(StrEnum):
    """제품 매칭 상태. 후보 수집 단계에서는 항상 `MANUAL_REVIEW_REQUIRED` 로 시작한다.

    네이버 쇼핑 검색 결과에는 전성분이 없어 자동으로 `MATCHED` 로 확정할 수 없기 때문이다.
    """

    MATCHED = "matched"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    REJECTED = "rejected"


class NaverShoppingItem(BaseModel):
    """`GET /v1/search/shop.json` 응답의 `items[]` 원소 하나."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    title: str
    link: str
    image: str
    lprice: str
    hprice: str
    mall_name: str = Field(alias="mallName")
    product_id: str = Field(alias="productId")
    product_type: str = Field(alias="productType")
    brand: str = ""
    maker: str = ""
    category1: str = ""
    category2: str = ""
    category3: str = ""
    category4: str = ""


class ProductCandidateRow(BaseModel):
    """`data/processed/product_candidates.csv` 한 행.

    아직 전성분을 검증하지 않은 후보다. `verified_products.csv` 로 옮기기 전까지
    추천에 사용하지 않는다 (`docs/data/data.md` 참고).
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    target_group: TargetGroup
    search_query: str
    naver_product_id: str
    raw_title: str
    brand: str
    maker: str
    category1: str
    category2: str
    category3: str
    lowest_price: int
    highest_price: int
    price_band: PriceBand
    volume_value: int | None = None
    volume_unit: str | None = None
    image_url: str
    shopping_url: str
    mall_name: str
    product_type: str
    observed_at: datetime
    match_status: MatchStatus
