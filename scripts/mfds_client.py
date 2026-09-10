"""`getCsmtcsUseRstrcInfoService` (식약처 화장품 사용제한 원료정보) 호출.

End Point: https://apis.data.go.kr/1471000/CsmtcsUseRstrcInfoService
파라미터(전부 필수): serviceKey, pageNo, numOfRows, type. 이 API는 성분명으로 필터링하는
파라미터가 없어, 대상 성분만 뽑아 받을 수 없다. 그래서 전체를 페이지네이션으로 순회한다.
"""

import httpx

from core.config import MfdsConfig
from scripts.evidence_schemas import MfdsRestrictedIngredientItem

_DEFAULT_PAGE_SIZE = 500  # API가 허용하는 numOfRows 최댓값(실측 확인함)
_DEFAULT_TIMEOUT_SECONDS = 30.0
_SUCCESS_RESULT_CODE = "00"


class MfdsApiError(RuntimeError):
    """MFDS API가 `resultCode != '00'`을 돌려줬을 때."""


class MfdsRestrictedIngredientClient:
    """페이지 단위 호출과 전체 순회를 모두 제공한다."""

    def __init__(
        self,
        config: MfdsConfig,
        page_size: int = _DEFAULT_PAGE_SIZE,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._config = config
        self._page_size = page_size
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def fetch_page(self, page_no: int) -> tuple[list[MfdsRestrictedIngredientItem], int]:
        """한 페이지를 가져온다. (아이템 목록, totalCount) 를 반환한다."""
        response = await self._client.get(
            self._config.base_url + "/getCsmtcsUseRstrcInfoService",
            params={
                "serviceKey": self._config.service_key,
                "pageNo": page_no,
                "numOfRows": self._page_size,
                "type": "json",
            },
        )
        response.raise_for_status()
        payload = response.json()

        header = payload["response"]["header"] if "response" in payload else payload["header"]
        result_code = header["resultCode"]
        if result_code != _SUCCESS_RESULT_CODE:
            raise MfdsApiError(f"MFDS API 오류: {result_code} {header.get('resultMsg')}")

        body = payload["response"]["body"] if "response" in payload else payload["body"]
        total_count = int(body["totalCount"])
        raw_items = body.get("items") or {}
        item_or_items = raw_items.get("item") if isinstance(raw_items, dict) else raw_items
        if item_or_items is None:
            return [], total_count
        if isinstance(item_or_items, dict):
            item_or_items = [item_or_items]

        return [
            MfdsRestrictedIngredientItem.model_validate(item) for item in item_or_items
        ], total_count

    async def fetch_all(self) -> list[MfdsRestrictedIngredientItem]:
        """전체 페이지를 순회해 모든 항목을 모은다."""
        items, total_count = await self.fetch_page(1)
        page_no = 1
        while len(items) < total_count:
            page_no += 1
            page_items, _ = await self.fetch_page(page_no)
            if not page_items:
                break
            items.extend(page_items)
        return items

    async def close(self) -> None:
        await self._client.aclose()
