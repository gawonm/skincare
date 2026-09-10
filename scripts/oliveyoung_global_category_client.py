"""올리브영 글로벌 카테고리 목록 API(`global.oliveyoung.com/display/category/product-data/`)
호출.

상품 상세(`detail-data`)와 같은 도메인이라 Cloudflare 봇 관리가 걸린 검색 API와 달리 쿠키
없이 일반 httpx로 호출된다(브라우저로 직접 확인함).
"""

import httpx

from scripts.oliveyoung_global_category_schemas import OliveYoungGlobalCategoryListResponse

_PRODUCT_DATA_URL = "https://global.oliveyoung.com/display/category/product-data/"
_REQUEST_TIMEOUT_SECONDS = 30.0
_LANG_CODE_EN = "en"
# "20"=New(등록일 최신순). "10"(Most Popular)은 실시간 판매량에 따라 실행 중에도 순서가
# 바뀔 수 있어, 페이지 경계가 흔들리지 않도록 등록일 기준 정렬을 쓴다.
_SORT_STANDARD_CODE_NEW = "20"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


class OliveYoungGlobalCategoryClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http_client = http_client or httpx.Client(
            timeout=_REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT}
        )

    def list_page(
        self, category_no: str, page_num: int, rows_per_page: int
    ) -> OliveYoungGlobalCategoryListResponse:
        """카테고리 하나(`category_no`)의 상품 목록을 한 페이지 가져온다."""
        try:
            response = self._http_client.post(
                _PRODUCT_DATA_URL,
                json={
                    "accParam": "",
                    "langCode": _LANG_CODE_EN,
                    "previewDate": "",
                    "encKey": "",
                    "encText": "",
                    "dlvCntry": "9999",
                    "mrgnCntryCode": "",
                    "ctgrNo": category_no,
                    "prdtSortStdrCode": _SORT_STANDARD_CODE_NEW,
                    "pageNum": page_num,
                    "rowsPerPage": str(rows_per_page),
                    "attrValNoList": {},
                    "brandNoList": [],
                    "ctgrNoList": [],
                    "eventSlprcDscntRt": [],
                    "reviewScore": [],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"올리브영 글로벌 카테고리 목록 조회 실패 "
                f"(ctgrNo={category_no!r}, pageNum={page_num}): {error}"
            ) from error

        return OliveYoungGlobalCategoryListResponse.model_validate(response.json())

    def close(self) -> None:
        self._http_client.close()
