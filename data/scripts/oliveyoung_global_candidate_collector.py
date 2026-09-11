"""성분군별 검색어로 올리브영 글로벌을 검색해 후보 목록을 모은다.

같은 성분군 안에서 동일한 상품 ID 가 여러 검색어에 걸리면 하나만 남긴다. 검색 결과 자체엔
정가·카테고리가 정확히 없어(할인가만 있고, 카테고리는 아예 없음), 후보로 남긴 상품마다
`get_product_detail` 을 한 번 더 불러 정가와 카테고리를 채운다. 전성분(INCI) 원문도
`get_ingredients_text` 로 같이 받아온다 — 별도 API(`product/description-info`)라 상품당
호출이 하나 더 늘어난다.
"""

from collections import Counter
from datetime import datetime

from data.scripts.oliveyoung_global_candidate_builder import OliveYoungGlobalCandidateBuilder
from data.scripts.oliveyoung_global_client import OliveYoungGlobalClient
from data.scripts.product_candidate_schemas import ProductCandidateRow, ReviewReason, TargetGroup

# 이 개수를 넘으면(즉 2개 이상 target_group 에 같은 상품이 걸리면) 상품명만으로는
# 어느 그룹에 해당하는지 구분할 수 없다는 뜻이라 ReviewReason.DUPLICATE_PRODUCT_ACROSS_GROUPS
# 를 붙인다.
_SINGLE_GROUP_COUNT = 1

# 네이버 쇼핑 수집기가 "C0001" 형식을 쓰므로, 같은 CSV 에 합쳤을 때 candidate_id 가
# 겹치지 않도록 접두사를 다르게 둔다.
_CANDIDATE_ID_PREFIX = "OY"


class OliveYoungGlobalCandidateCollector:
    def __init__(
        self,
        client: OliveYoungGlobalClient,
        builder: OliveYoungGlobalCandidateBuilder,
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
                    seen_keys.add(dedupe_key)

                    detail = self._client.get_product_detail(item.product_id)
                    raw_ingredients_text = self._client.get_ingredients_text(item.product_id)
                    rows.append(
                        self._builder.build(
                            candidate_id=f"{_CANDIDATE_ID_PREFIX}{len(rows) + 1:04d}",
                            target_group=target_group,
                            search_query=query,
                            detail=detail,
                            raw_ingredients_text=raw_ingredients_text,
                            observed_at=observed_at,
                        )
                    )

        return self._flag_cross_group_duplicates(rows)

    def _flag_cross_group_duplicates(
        self, rows: list[ProductCandidateRow]
    ) -> list[ProductCandidateRow]:
        # target_group 이 다르면 seen_keys 로는 안 걸러지므로, 같은 상품이 여러
        # 그룹에 들어간 경우를 여기서 따로 찾아 표시한다 (frozen 모델이라 model_copy 로
        # 새 인스턴스를 만든다).
        product_id_counts = Counter(row.source_product_id for row in rows)
        return [
            row.model_copy(
                update={
                    "review_reasons": (
                        *row.review_reasons,
                        ReviewReason.DUPLICATE_PRODUCT_ACROSS_GROUPS,
                    )
                }
            )
            if product_id_counts[row.source_product_id] > _SINGLE_GROUP_COUNT
            else row
            for row in rows
        ]
