"""성분군별 검색어로 네이버 쇼핑을 검색해 후보 목록을 모은다.

같은 성분군 안에서 동일한 `naver_product_id` 가 여러 검색어에 걸리면 하나만 남긴다.
"""

from datetime import datetime

from scripts.naver_shopping_candidate_builder import ProductCandidateBuilder
from scripts.naver_shopping_client import NaverShoppingClient
from scripts.product_candidate_schemas import ProductCandidateRow, TargetGroup


class ProductCandidateCollector:
    def __init__(
        self,
        client: NaverShoppingClient,
        builder: ProductCandidateBuilder,
        search_queries: dict[TargetGroup, tuple[str, ...]],
    ) -> None:
        self._client = client
        self._builder = builder
        self._search_queries = search_queries

    def collect(self) -> list[ProductCandidateRow]:
        rows: list[ProductCandidateRow] = []
        seen_keys: set[tuple[TargetGroup, str]] = set()
        observed_at = datetime.now().astimezone()

        for target_group, queries in self._search_queries.items():
            for query in queries:
                for item in self._client.search(query):
                    dedupe_key = (target_group, item.product_id)
                    if dedupe_key in seen_keys:
                        continue

                    candidate = self._builder.build(
                        candidate_id=f"C{len(rows) + 1:04d}",
                        target_group=target_group,
                        search_query=query,
                        item=item,
                        observed_at=observed_at,
                    )
                    if candidate is None:
                        continue

                    seen_keys.add(dedupe_key)
                    rows.append(candidate)

        return rows
