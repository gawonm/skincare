"""올리브영 글로벌 카테고리 목록(`display/category/product-data/`) 응답이 주고받는
Pydantic 모델.

검색(`unified-search`)과는 별도 API다. 카테고리 하나(`ctgrNo`)를 페이지 단위로 순회하며
그 카테고리에 노출된 전체 상품을 가져온다 — `allPathCtgrNoList`에 상품이 속한 모든
카테고리(가상 "Trend Keyword" 경로 포함)가 이미 들어 있어, 최상위 카테고리 하나만
순회하면 하위 카테고리를 따로 순회하지 않아도 전량을 중복 없이 얻는다.
"""

from pydantic import BaseModel, ConfigDict, Field


class OliveYoungGlobalCategoryHitFields(BaseModel):
    """`hits.hit[].fields` 원소. 목록 화면에 필요한 최소 정보만 내려온다 — 옵션별 가격이나
    전성분은 없어 적격 상품만 골라 상세/전성분 API를 따로 불러야 한다."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    prdt_no: str = Field(alias="prdtNo")
    prdt_name: str = Field(alias="prdtName")
    brand_name: str = Field(alias="brandName")
    # 상품이 속한 모든 카테고리 번호(가상 "Trend Keyword" 경로 포함). Gift Set(1000000012)
    # 소속 여부를 이 목록으로 판별한다.
    all_path_ctgr_no_list: list[str] = Field(default_factory=list, alias="allPathCtgrNoList")
    sell_stat_code: str = Field(alias="sellStatCode")
    sold_out_yn: str = Field(alias="soldOutYn")
    srch_psblt_yn: str = Field(alias="srchPsbltYn")
    # "Y"면 옵션이 2개 이상이라는 뜻(상품 상세를 불러야 정확한 개수를 안다).
    optn_yn: str = Field(alias="optnYn")


class OliveYoungGlobalCategoryHit(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    fields: OliveYoungGlobalCategoryHitFields


class OliveYoungGlobalCategoryHits(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    found: int
    start: int
    hit: list[OliveYoungGlobalCategoryHit] = Field(default_factory=list)


class OliveYoungGlobalCategoryListResponse(BaseModel):
    """`POST display/category/product-data/` 응답 전체. facet 등 목록 화면 전용 필드는
    수집에 쓰지 않아 모델에 넣지 않는다."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    hits: OliveYoungGlobalCategoryHits
