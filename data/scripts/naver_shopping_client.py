"""네이버 쇼핑 검색 API 호출.

인증 정보는 환경변수로만 관리한다 (`docs/data/data.md` 참고). `.env` 파일은 docker-compose
전용이라 애플리케이션이 자동으로 읽지 않으므로, 이 스크립트를 실행하는 셸에
`NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` 을 직접 export 해야 한다.
"""

import os

import httpx
from pydantic import BaseModel, ConfigDict

from data.scripts.naver_shopping_schemas import NaverShoppingItem


class NaverShoppingCredentials(BaseModel):
    """환경변수에서 읽은 네이버 API 인증 정보. 로그에 그대로 출력하지 않는다."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    client_secret: str

    @classmethod
    def from_env(cls) -> "NaverShoppingCredentials":
        client_id = os.environ.get("NAVER_CLIENT_ID")
        client_secret = os.environ.get("NAVER_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError(
                "NAVER_CLIENT_ID/NAVER_CLIENT_SECRET 환경변수가 없습니다. "
                "셸에 직접 export 하세요 (.env 파일은 docker-compose 전용이라 자동으로 읽지 않습니다)."
            )
        return cls(client_id=client_id, client_secret=client_secret)


class NaverShoppingClient:
    """`GET /v1/search/shop.json` 호출. 중고·렌탈·해외직구는 요청 단계에서 제외한다."""

    _SEARCH_URL = "https://openapi.naver.com/v1/search/shop.json"
    _MAX_DISPLAY_COUNT = 100
    _SORT_BY_SIMILARITY = "sim"
    _EXCLUDED_PRODUCT_TYPES = "used:rental:cbshop"
    _REQUEST_TIMEOUT_SECONDS = 30.0

    def __init__(
        self, credentials: NaverShoppingCredentials, http_client: httpx.Client | None = None
    ) -> None:
        self._credentials = credentials
        self._http_client = http_client or httpx.Client(timeout=self._REQUEST_TIMEOUT_SECONDS)

    def search(self, query: str) -> list[NaverShoppingItem]:
        try:
            response = self._http_client.get(
                self._SEARCH_URL,
                headers={
                    "X-Naver-Client-Id": self._credentials.client_id.strip(),
                    "X-Naver-Client-Secret": self._credentials.client_secret.strip(),
                },
                params={
                    "query": query,
                    "display": self._MAX_DISPLAY_COUNT,
                    "sort": self._SORT_BY_SIMILARITY,
                    "exclude": self._EXCLUDED_PRODUCT_TYPES,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(f"네이버 쇼핑 검색 실패 (query={query!r}): {error}") from error

        items = response.json().get("items", [])
        return [NaverShoppingItem.model_validate(item) for item in items]

    def close(self) -> None:
        self._http_client.close()
