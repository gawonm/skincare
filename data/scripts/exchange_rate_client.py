"""Frankfurter 환율 API 호출.

인증 키가 필요 없는 무료 API(ECB 데이터 기반)라 자격 증명 관리가 필요 없다.
호출 빈도를 낮추기 위해 상품 하나마다 부르지 말고, 세션당 한 번만 불러서 재사용해야
한다 (`OliveYoungGlobalClient._ensure_exchange_rate` 참고).
"""

import httpx


class ExchangeRateClient:
    """`GET /v1/latest` 호출로 기준 통화 대비 환율을 가져온다."""

    _LATEST_RATES_URL = "https://api.frankfurter.dev/v1/latest"
    _REQUEST_TIMEOUT_SECONDS = 10.0

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http_client = http_client or httpx.Client(timeout=self._REQUEST_TIMEOUT_SECONDS)

    def get_usd_to_krw_rate(self) -> float:
        try:
            response = self._http_client.get(
                self._LATEST_RATES_URL,
                params={"base": "USD", "symbols": "KRW"},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(f"USD/KRW 환율 조회 실패: {error}") from error

        body = response.json()
        rate = body.get("rates", {}).get("KRW")
        if rate is None:
            raise RuntimeError(f"USD/KRW 환율 조회 실패: 응답에 KRW 환율이 없습니다 ({body})")

        return float(rate)

    def close(self) -> None:
        self._http_client.close()
