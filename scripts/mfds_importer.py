"""`MfdsRestrictedIngredientItem` 목록을 `IngredientMaster`에 매칭해 `Evidence`로 적재한다.

이 API는 재실행할 때마다 안정적인 자연키가 없어(같은 성분이 국가마다 여러 행으로 나오고,
같은 성분·국가에도 고시원료명이 다르면 별도 행일 수 있다) upsert 대신, 이전에 적재한
MFDS 출처 `Evidence`를 지우고 새로 채우는 전체 새로고침 방식을 쓴다.
"""

import csv
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.evidence import Evidence, EvidenceSourceType, EvidenceTopic
from scripts.evidence_schemas import MfdsImportSummary, MfdsRestrictedIngredientItem
from scripts.ingredient_name_matcher import IngredientNameMatcher
from scripts.ingredient_schemas import IngredientMatchResult

_SOURCE_TITLE = "식품의약품안전처 화장품 사용제한 원료정보"
_SOURCE_URL = "https://www.data.go.kr/data/15111772/openapi.do"
_REVIEW_QUEUE_HEADER = (
    "ingredient_standard_name",
    "ingredient_english_name",
    "country_name",
    "match_method",
    "review_candidate_ids",
)


class MfdsRestrictedIngredientImporter:
    """`Evidence` 새로고침 담당. commit 은 호출한 쪽에서 한다."""

    def __init__(
        self,
        session: AsyncSession,
        matcher: IngredientNameMatcher,
        review_queue_path: Path,
    ) -> None:
        self._session = session
        self._matcher = matcher
        self._review_queue_path = review_queue_path

    async def import_items(self, items: list[MfdsRestrictedIngredientItem]) -> MfdsImportSummary:
        await self._session.execute(
            delete(Evidence).where(
                Evidence.source_type == EvidenceSourceType.MFDS_RESTRICTED_INGREDIENT
            )
        )

        rows_to_insert: list[dict[str, object]] = []
        review_entries: list[tuple[MfdsRestrictedIngredientItem, IngredientMatchResult]] = []

        for item in items:
            result = self._matcher.match(
                item.ingredient_standard_name, item.ingredient_english_name
            )
            if result.matched_ingredient_id is None:
                review_entries.append((item, result))
                continue
            rows_to_insert.append(self._build_row(item, result.matched_ingredient_id))

        if rows_to_insert:
            await self._session.execute(insert(Evidence), rows_to_insert)

        self._write_review_queue(review_entries)

        return MfdsImportSummary(
            total_items=len(items),
            inserted=len(rows_to_insert),
            manual_review=len(review_entries),
        )

    def _build_row(
        self, item: MfdsRestrictedIngredientItem, ingredient_id: UUID
    ) -> dict[str, object]:
        conditions = "\n".join(
            part for part in (item.provision_article, item.limit_condition) if part
        )
        return {
            "ingredient_id": ingredient_id,
            "topic": EvidenceTopic.COSMETIC_USE_RESTRICTION,
            "claim": f"{item.country_name} 배합 규제: {item.regulate_type_label}",
            "conditions": conditions or None,
            "jurisdiction": item.country_name,
            "regulate_type": item.regulate_type,
            "cas_no": item.cas_no,
            "ingredient_synonym": item.ingredient_synonym,
            "notice_ingredient_name": item.notice_ingredient_name,
            "source_type": EvidenceSourceType.MFDS_RESTRICTED_INGREDIENT,
            "source_title": _SOURCE_TITLE,
            "source_url": _SOURCE_URL,
        }

    def _write_review_queue(
        self, review_entries: list[tuple[MfdsRestrictedIngredientItem, IngredientMatchResult]]
    ) -> None:
        self._review_queue_path.parent.mkdir(parents=True, exist_ok=True)
        with self._review_queue_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(_REVIEW_QUEUE_HEADER)
            for item, result in review_entries:
                writer.writerow(
                    (
                        item.ingredient_standard_name,
                        item.ingredient_english_name or "",
                        item.country_name,
                        result.method.value,
                        "|".join(str(candidate_id) for candidate_id in result.review_candidate_ids),
                    )
                )
