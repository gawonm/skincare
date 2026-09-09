"""올리브영 글로벌(global.oliveyoung.com) 검색·상품 상세 API 호출.

두 API 는 필요한 실행 환경이 다르다.

- 상품 상세(`global.oliveyoung.com/product/detail-data`): 쿠키 없이도 열려 있어 순수
  HTTP 요청(httpx)으로 충분하다.
- 검색(`cbe-external-api.oliveyoung.com/.../unified-search`): Cloudflare 봇 관리가
  걸려 있다. `cf_clearance` 쿠키를 httpx 로 재사용해도 403 이 나는데, 이 엔드포인트가
  브라우저의 실제 JS 실행 컨텍스트에서 나온 `fetch` 요청만 통과시키기 때문이다
  (Playwright 의 별도 `APIRequestContext` 로 같은 쿠키를 써도 막힌다 — 직접 확인함).
  그래서 검색은 매번 Playwright 로 연 페이지 안에서 `page.evaluate` 로 `fetch` 를
  실행한다. 브라우저 세션은 첫 검색 때 한 번만 띄우고 이후 호출에서 재사용한다.

올리브영 글로벌은 원화(KRW)를 지원하지 않는 해외 판매 사이트라 모든 가격이 USD 로
내려온다. 이 클라이언트는 `ExchangeRateClient` 로 조회한 환율을 곱해 `*_krw` 필드를
채워 넣는다. 환율은 세션당 한 번만 조회해서 캐시한다 (매 상품마다 부르면 낭비다).
"""

import json
import time

import httpx
from playwright.sync_api import Playwright, sync_playwright

from scripts.exchange_rate_client import ExchangeRateClient
from scripts.oliveyoung_global_schemas import (
    OliveYoungGlobalDescriptionItem,
    OliveYoungGlobalProductDetail,
    OliveYoungGlobalSearchItem,
)


class OliveYoungGlobalClient:
    """검색 결과와 상품 상세를 조회한다. 한국 올리브영 메인 도메인은 다루지 않는다."""

    _SEARCH_URL = (
        "https://cbe-external-api.oliveyoung.com/display/v1/search/products/unified-search"
    )
    _DETAIL_URL = "https://global.oliveyoung.com/product/detail-data"
    _DESCRIPTION_URL = "https://global.oliveyoung.com/product/description-info"
    # description-info 응답 안에서 전성분(INCI) 항목을 가리키는 라벨. 상품마다 코드번호
    # (prdtNotcItemCode)는 "045"로 관찰됐지만 상품 유형에 따라 달라질 수 있어, 코드보다
    # 안정적인 라벨 문자열로 찾는다.
    _INGREDIENTS_LABEL = "Ingredients"
    # Cloudflare 클리어런스 쿠키를 발급받기 위해 최초 1회만 여는 페이지. 검색 결과가
    # 실제로 필요한 페이지는 아니고, 클리어런스 쿠키를 심는 용도다.
    _CLEARANCE_BOOTSTRAP_URL = "https://global.oliveyoung.com/kr/search/results?query=serum"
    _USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    )
    _REQUEST_TIMEOUT_SECONDS = 30.0
    _LANG_CODE_EN = "en"
    _SEARCH_SUCCESS_CODE = "OK"
    _CLOUDFLARE_CLEARANCE_COOKIE_NAME = "cf_clearance"
    _CHALLENGE_POLL_TIMEOUT_SECONDS = 30
    _CHALLENGE_POLL_INTERVAL_SECONDS = 1
    _EXPECTED_CURRENCY_SYMBOL = "US$"

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        exchange_rate_client: ExchangeRateClient | None = None,
    ) -> None:
        self._http_client = http_client or httpx.Client(
            timeout=self._REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": self._USER_AGENT},
        )
        self._exchange_rate_client = exchange_rate_client or ExchangeRateClient()
        self._usd_to_krw_rate: float | None = None
        self._playwright: Playwright | None = None
        self._search_page = None

    def search(self, query: str) -> list[OliveYoungGlobalSearchItem]:
        """검색어로 상품 목록을 가져온다. 응답에 가격이 포함돼 있어 상세 조회 없이도 쓸 수 있다."""
        page = self._ensure_search_page()
        result = page.evaluate(
            """
            async (args) => {
                const res = await fetch(args.url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query: args.query}),
                });
                return {status: res.status, body: await res.text()};
            }
            """,
            {"url": self._SEARCH_URL, "query": query},
        )

        if result["status"] != httpx.codes.OK:
            raise RuntimeError(
                f"올리브영 글로벌 검색 실패 (query={query!r}, status={result['status']}): "
                f"{result['body'][:200]}"
            )

        body = json.loads(result["body"])
        if body.get("code") != self._SEARCH_SUCCESS_CODE:
            raise RuntimeError(f"올리브영 글로벌 검색 실패 (query={query!r}): {body}")

        products = body["data"]["products"]
        return [self._build_search_item(product) for product in products]

    def get_product_detail(self, prdt_no: str) -> OliveYoungGlobalProductDetail:
        """상품 번호로 상세(옵션별 가격 포함)를 가져온다. 쿠키가 없어도 호출된다."""
        try:
            response = self._http_client.post(
                self._DETAIL_URL,
                json={"prdtNo": prdt_no, "langCode": self._LANG_CODE_EN},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"올리브영 글로벌 상품 상세 조회 실패 (prdtNo={prdt_no!r}): {error}"
            ) from error

        body = response.json()
        product = body.get("product")
        if product is None:
            raise RuntimeError(f"올리브영 글로벌 상품 상세 조회 실패 (prdtNo={prdt_no!r}): {body}")

        return self._build_product_detail(product)

    def get_ingredients_text(self, prdt_no: str) -> str | None:
        """상품 번호로 전성분(INCI) 원문을 가져온다. 쿠키가 없어도 호출된다.

        옵션이 여러 개인 상품은 `[옵션명]` 단위로 옵션별 전성분이 한 문자열 안에 줄바꿈으로
        이어져 있다 — 옵션별로 쪼개지 않고 원문 그대로 돌려준다(파싱은 호출자 책임).
        고시 항목 목록에 "Ingredients" 라벨이 아예 없는 상품이면 `None`.
        """
        try:
            response = self._http_client.post(
                self._DESCRIPTION_URL,
                json={"prdtNo": prdt_no, "langCode": self._LANG_CODE_EN},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"올리브영 글로벌 전성분 조회 실패 (prdtNo={prdt_no!r}): {error}"
            ) from error

        body = response.json()
        items = body.get("description")
        if items is None:
            raise RuntimeError(f"올리브영 글로벌 전성분 조회 실패 (prdtNo={prdt_no!r}): {body}")

        for item in items:
            description_item = OliveYoungGlobalDescriptionItem.model_validate(item)
            if description_item.code_dtl_name == self._INGREDIENTS_LABEL:
                return description_item.item_cont
        return None

    def _build_search_item(self, product: dict) -> OliveYoungGlobalSearchItem:
        price_info = dict(product["priceInfo"])
        currency_symbol = price_info.get("currencySymbol")
        if currency_symbol != self._EXPECTED_CURRENCY_SYMBOL:
            raise RuntimeError(
                f"예상치 못한 통화입니다 (currencySymbol={currency_symbol!r}). "
                f"{self._EXPECTED_CURRENCY_SYMBOL} 만 지원합니다."
            )

        rate = self._ensure_exchange_rate()
        price_info["main_price_krw"] = self._convert_usd_to_krw(price_info["mainPrice"], rate)
        sub_price = price_info.get("subPrice")
        price_info["sub_price_krw"] = (
            self._convert_usd_to_krw(sub_price, rate) if sub_price is not None else None
        )

        merged_product = dict(product)
        merged_product["priceInfo"] = price_info
        return OliveYoungGlobalSearchItem.model_validate(merged_product)

    def _build_product_detail(self, product: dict) -> OliveYoungGlobalProductDetail:
        rate = self._ensure_exchange_rate()

        merged_product = dict(product)
        merged_product["normal_amount_krw"] = self._convert_usd_to_krw(product["nrmlAmt"], rate)
        merged_product["sale_amount_krw"] = self._convert_usd_to_krw(product["saleAmt"], rate)
        merged_product["optionList"] = [
            {
                **option,
                "normal_amount_krw": self._convert_usd_to_krw(option["nrmlAmt"], rate),
                "sale_amount_krw": self._convert_usd_to_krw(option["saleAmt"], rate),
            }
            # optionList 는 옵션 없는 단일 상품이면 키 자체가 아니라 값이 None 으로 온다.
            for option in product.get("optionList") or []
        ]
        return OliveYoungGlobalProductDetail.model_validate(merged_product)

    def _ensure_exchange_rate(self) -> float:
        if self._usd_to_krw_rate is None:
            self._usd_to_krw_rate = self._exchange_rate_client.get_usd_to_krw_rate()
        return self._usd_to_krw_rate

    @staticmethod
    def _convert_usd_to_krw(usd_amount: str | float, rate: float) -> int:
        # 옵션이 여러 개인 상품은 검색 결과의 mainPrice/subPrice 가 "6.60 - 8.40" 같은
        # 범위 문자열로 온다. 상세 조회에서 옵션별 정확한 가격을 다시 받으므로, 검색
        # 단계에서는 대표값으로 최저가(범위의 첫 숫자)만 변환해도 충분하다.
        first_amount = str(usd_amount).split("-")[0].strip()
        return round(float(first_amount) * rate)

    def _ensure_search_page(self):
        if self._search_page is not None:
            return self._search_page

        self._playwright = sync_playwright().start()
        browser = self._playwright.chromium.launch(
            headless=True,
            # navigator.webdriver 를 숨기지 않으면 Cloudflare 봇 탐지에 걸려 클리어런스
            # 쿠키가 발급되지 않는다.
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(user_agent=self._USER_AGENT)
        page = context.new_page()
        page.goto(self._CLEARANCE_BOOTSTRAP_URL, wait_until="load")

        # 클리어런스 쿠키는 페이지 로드 후 챌린지가 비동기로 끝나야 심어진다.
        # cf_clearance 는 HttpOnly 라 document.cookie 로는 안 보이므로 context.cookies()
        # 를 직접 폴링한다.
        deadline = time.monotonic() + self._CHALLENGE_POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            cookie_names = {cookie["name"] for cookie in context.cookies()}
            if self._CLOUDFLARE_CLEARANCE_COOKIE_NAME in cookie_names:
                break
            time.sleep(self._CHALLENGE_POLL_INTERVAL_SECONDS)
        else:
            raise RuntimeError(
                f"{self._CLOUDFLARE_CLEARANCE_COOKIE_NAME} 쿠키 발급 대기 시간 초과. "
                "Cloudflare 챌린지 방식이 바뀌었을 수 있습니다."
            )

        self._search_page = page
        return page

    def close(self) -> None:
        self._http_client.close()
        self._exchange_rate_client.close()
        if self._playwright is not None:
            self._playwright.stop()
