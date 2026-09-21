"""NCBI E-utilities(ESearch/EFetch) 호출. 공식 API 만 쓴다.

API key 없이는 초당 3회 제한이라 요청 사이에 간격을 둔다. 실패는 재시도하되 계속 실패하면
그대로 예외를 낸다(CLAUDE.md 규칙 7).
"""

import time
from typing import Protocol

import httpx

from data.scripts.evidence_collector_schemas import PubmedRecord
from data.scripts.pubmed_xml_parser import PubmedXmlParser


class PubmedSource(Protocol):
    """collector 가 의존하는 최소 인터페이스. 테스트는 네트워크 없이 이 인터페이스를 대체한다."""

    def search(self, query: str, retmax: int) -> list[str]: ...

    def fetch(self, pmids: list[str]) -> list[PubmedRecord]: ...


class PubmedClient:
    _BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    _TOOL_NAME = "skincare-evidence-collector"
    _REQUEST_TIMEOUT_SECONDS = 30.0
    # 키 없는 NCBI 한도(3 req/s)보다 여유를 둔 간격
    _MIN_REQUEST_INTERVAL_SECONDS = 0.4
    _MAX_ATTEMPTS = 3
    _RETRY_BACKOFF_SECONDS = 2.0
    _RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http = http_client or httpx.Client(timeout=self._REQUEST_TIMEOUT_SECONDS)
        self._parser = PubmedXmlParser()
        self._last_request_at = 0.0
        self.request_count = 0

    def search(self, query: str, retmax: int) -> list[str]:
        response = self._get(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmax": retmax,
                "retmode": "json",
                "sort": "relevance",
            },
        )
        try:
            return list(response.json()["esearchresult"]["idlist"])
        except (ValueError, KeyError) as e:
            raise RuntimeError(f"PubMed ESearch 응답 형식이 예상과 다릅니다: {e}") from e

    def fetch(self, pmids: list[str]) -> list[PubmedRecord]:
        if not pmids:
            return []
        response = self._get(
            "efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
        )
        return self._parser.parse(response.text)

    def _get(self, endpoint: str, params: dict[str, str | int]) -> httpx.Response:
        url = f"{self._BASE_URL}/{endpoint}"
        query = {**params, "tool": self._TOOL_NAME}
        last_error: Exception | None = None
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            self._wait_for_rate_limit()
            self.request_count += 1
            try:
                response = self._http.get(url, params=query)
                if response.status_code not in self._RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    return response
                last_error = RuntimeError(f"HTTP {response.status_code}")
            except httpx.TransportError as e:
                last_error = e
            time.sleep(self._RETRY_BACKOFF_SECONDS * attempt)
        raise RuntimeError(
            f"PubMed {endpoint} 호출이 {self._MAX_ATTEMPTS}회 모두 실패했습니다: {last_error}"
        ) from last_error

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(self._MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()
