"""`KnowledgedataRow` 목록을 `IngredientMaster`에 매칭해 `IngredientKnowledgeFact`로 적재한다.

매칭에 실패한 행(`IngredientMatchMethod.MANUAL_REVIEW`)은 DB에 넣지 않고 CSV 검토 큐로
내보낸다. `docs/data.md`가 정한 `data/manual_review/` 관례를 따른다.
"""

import csv
from pathlib import Path
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingredient_knowledge import IngredientKnowledgeFact, RegulatoryConfidence
from scripts.ingredient_name_matcher import IngredientNameMatcher
from scripts.ingredient_schemas import (
    IngredientMatchResult,
    KnowledgedataImportSummary,
    KnowledgedataRow,
)

_REVIEW_QUEUE_HEADER = (
    "source_row_no",
    "inci_name",
    "name_ko",
    "match_method",
    "review_candidate_ids",
)


class KnowledgedataImporter:
    """`IngredientKnowledgeFact` upsert 담당. commit 은 호출한 쪽에서 한다."""

    def __init__(
        self,
        session: AsyncSession,
        matcher: IngredientNameMatcher,
        review_queue_path: Path,
    ) -> None:
        self._session = session
        self._matcher = matcher
        self._review_queue_path = review_queue_path

    async def import_rows(self, rows: list[KnowledgedataRow]) -> KnowledgedataImportSummary:
        matched = 0
        review_entries: list[tuple[KnowledgedataRow, IngredientMatchResult]] = []

        for row in rows:
            result = self._matcher.match(row.name_ko, row.inci_name)
            if result.matched_ingredient_id is not None:
                await self._upsert_fact(row, result.matched_ingredient_id)
                matched += 1
            else:
                review_entries.append((row, result))

        self._write_review_queue(review_entries)

        return KnowledgedataImportSummary(
            total_rows=len(rows),
            matched=matched,
            manual_review=len(review_entries),
        )

    async def _upsert_fact(self, row: KnowledgedataRow, ingredient_id: UUID) -> None:
        values = {
            "ingredient_id": ingredient_id,
            "source_row_no": row.source_row_no,
            "inci_name": row.inci_name,
            "name_ko": row.name_ko,
            "chemical_properties": row.chemical_properties,
            "product_characteristics": row.product_characteristics,
            "solubility": row.solubility,
            "molecular_formula": row.molecular_formula,
            "molecular_weight": row.molecular_weight,
            "efficacy": row.efficacy,
            "recommended_skin_types": row.recommended_skin_types,
            "precautions": row.precautions,
            "recommended_concentration": row.recommended_concentration,
            "compounding_regulation_text": row.compounding_regulation_text,
            "raw_material_source": row.raw_material_source,
            "source_reference": row.source_reference,
            "copyright_resolution": row.copyright_resolution,
            "token_count": row.token_count,
            "regulatory_confidence": RegulatoryConfidence.UNVERIFIED,
        }
        update_values = {**values, "updated_at": func.now()}
        del update_values["source_row_no"]

        statement = insert(IngredientKnowledgeFact).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_ingredient_knowledge_fact_source_row_no",
            set_=update_values,
        )
        await self._session.execute(statement)

    def _write_review_queue(
        self, review_entries: list[tuple[KnowledgedataRow, IngredientMatchResult]]
    ) -> None:
        self._review_queue_path.parent.mkdir(parents=True, exist_ok=True)
        with self._review_queue_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(_REVIEW_QUEUE_HEADER)
            for row, result in review_entries:
                writer.writerow(
                    (
                        row.source_row_no,
                        row.inci_name,
                        row.name_ko or "",
                        result.method.value,
                        "|".join(str(candidate_id) for candidate_id in result.review_candidate_ids),
                    )
                )
