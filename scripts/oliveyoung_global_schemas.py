"""올리브영 글로벌(global.oliveyoung.com) 수집 단계가 주고받는 Pydantic 모델.

이 사이트는 두 개의 서로 다른 API 를 쓴다:
- 검색: `cbe-external-api.oliveyoung.com` (Cloudflare 봇 관리가 걸려 있어 Playwright 로
  연 브라우저 세션 안에서만 호출된다. `oliveyoung_global_client.py` 참고)
- 상품 상세: `global.oliveyoung.com/product/detail-data` (쿠키 없이도 호출된다)

한국 올리브영 메인 도메인(oliveyoung.co.kr)은 첫 요청부터 403 이 나서 별도로 대응하지
않는다.

올리브영 글로벌은 원화(KRW)를 아예 지원하지 않는 해외 판매 사이트다(`/common/currencies`
에 USD/AUD/CAD 등 18개 통화만 있고 KRW 없음). `*_krw` 필드는 API 가 내려주는 값이 아니라
`OliveYoungGlobalClient` 가 환율을 곱해 계산한 값이다.
"""

from pydantic import BaseModel, ConfigDict, Field


class OliveYoungGlobalSearchPrice(BaseModel):
    """검색 결과 한 상품의 `priceInfo`."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    currency_symbol: str = Field(alias="currencySymbol")
    is_sale: bool = Field(alias="isSale")
    main_price: str = Field(alias="mainPrice")
    sub_price: str | None = Field(default=None, alias="subPrice")
    # 환율 변환값. API 응답에 없고 클라이언트가 계산해서 채운다.
    main_price_krw: int
    sub_price_krw: int | None = None


class OliveYoungGlobalSearchItem(BaseModel):
    """`POST /display/v1/search/products/unified-search` 응답의 `data.products[]` 원소."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    product_id: str = Field(alias="productId")
    product_name: str = Field(alias="productName")
    original_product_name: str = Field(alias="originalProductName")
    brand_name: str = Field(alias="brandName")
    price_info: OliveYoungGlobalSearchPrice = Field(alias="priceInfo")
    discount_rate: float = Field(alias="discountRate")
    is_sold_out: bool = Field(alias="isSoldOut")
    review_count: int = Field(alias="reviewCount")
    review_score: float = Field(alias="reviewScore")
    image_path: str = Field(alias="imagePath")


class OliveYoungGlobalProductOption(BaseModel):
    """`detail-data` 응답의 `optionList[]` 원소. 옵션별로 가격이 달라질 수 있다."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    gds_cd: str = Field(alias="gdsCd")
    option_name: str = Field(alias="snglOptnNameEn")
    normal_amount: float = Field(alias="nrmlAmt")
    sale_amount: float = Field(alias="saleAmt")
    sold_out_flag: str = Field(alias="tempOutOfStockYn", default="N")
    # 환율 변환값. API 응답에 없고 클라이언트가 계산해서 채운다.
    normal_amount_krw: int
    sale_amount_krw: int

    @property
    def is_sold_out(self) -> bool:
        return self.sold_out_flag == "Y"


class OliveYoungGlobalProductDetail(BaseModel):
    """`POST global.oliveyoung.com/product/detail-data` 응답의 `product` 필드."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    prdt_no: str = Field(alias="prdtNo")
    product_name: str = Field(alias="prdtNameEn")
    brand_name: str = Field(alias="brandNameEn")
    normal_amount: float = Field(alias="nrmlAmt")
    sale_amount: float = Field(alias="saleAmt")
    image_path: str = Field(alias="imagePath")
    # HTML 엔티티(`&gt;`)로 이어진 카테고리 경로. 예: "OliveYoungGlobal &gt; Face Masks &gt; Sheet Masks"
    category_path_en: str = Field(alias="allPathCtgrNameEn")
    option_list: list[OliveYoungGlobalProductOption] = Field(
        alias="optionList", default_factory=list
    )
    # 환율 변환값. API 응답에 없고 클라이언트가 계산해서 채운다.
    normal_amount_krw: int
    sale_amount_krw: int
