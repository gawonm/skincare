"""네이버 쇼핑 검색 API 응답 모델. 후보 수집 공통 모델은 `product_candidate_schemas.py`."""

from pydantic import BaseModel, ConfigDict, Field


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
