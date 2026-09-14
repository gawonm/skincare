"""성분 데이터 전체(IngredientMaster + IngredientKnowledgeFact + Evidence)를 RDB에서
읽어 POC용 CSV 하나로 합친다. RAG/LLM을 거치지 않고 DB 조회 결과만 쓴다.

사용법:
    uv run python -m data.scripts.export_ingredient_dataset
"""

import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from core.config import settings
from core.database import Database
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.ingredient_knowledge_fact_repository import (
    IngredientKnowledgeFactRepository,
)
from data.scripts.ingredient_dataset_csv_writer import IngredientDatasetCsvWriter
from data.scripts.ingredient_master_reader import IngredientMasterReader
from data.scripts.ingredient_schemas import IngredientDatasetRow
from models.evidence import Evidence
from models.ingredient import IngredientMaster
from models.ingredient_knowledge import IngredientKnowledgeFact

_OUTPUT_PATH = Path("data/processed/ingredient_full.csv")
_LIST_SEPARATOR = "|"


class IngredientDatasetExporter:
    """세 테이블을 성분 1건 = 1행 기준으로 합쳐 `IngredientDatasetRow` 목록을 만든다."""

    def build_rows(
        self,
        ingredients: list[IngredientMaster],
        facts: list[IngredientKnowledgeFact],
        evidences: list[Evidence],
    ) -> list[IngredientDatasetRow]:
        facts_by_ingredient = self._group_first(facts, key=lambda fact: fact.ingredient_id)
        evidences_by_ingredient: dict[UUID, list[Evidence]] = defaultdict(list)
        for evidence in evidences:
            evidences_by_ingredient[evidence.ingredient_id].append(evidence)

        rows = []
        for ingredient in ingredients:
            fact = facts_by_ingredient.get(ingredient.id)
            ingredient_evidences = evidences_by_ingredient.get(ingredient.id, [])
            rows.append(
                IngredientDatasetRow(
                    ingredient_id=ingredient.id,
                    ingredient_code=ingredient.ingredient_code,
                    standard_name_ko=ingredient.standard_name_ko,
                    standard_name_en=ingredient.standard_name_en,
                    old_names_ko=_LIST_SEPARATOR.join(ingredient.old_names_ko),
                    old_names_en=_LIST_SEPARATOR.join(ingredient.old_names_en),
                    source_version=ingredient.source_version,
                    knowledge_inci_name=fact.inci_name if fact else None,
                    knowledge_efficacy=fact.efficacy if fact else None,
                    knowledge_recommended_skin_types=(
                        fact.recommended_skin_types if fact else None
                    ),
                    knowledge_precautions=fact.precautions if fact else None,
                    knowledge_recommended_concentration=(
                        fact.recommended_concentration if fact else None
                    ),
                    knowledge_regulatory_confidence=(
                        fact.regulatory_confidence.value if fact else None
                    ),
                    evidence_count=len(ingredient_evidences),
                    evidence_jurisdictions=_LIST_SEPARATOR.join(
                        evidence.jurisdiction for evidence in ingredient_evidences
                    ),
                    evidence_claims=_LIST_SEPARATOR.join(
                        f"{evidence.jurisdiction}: {evidence.claim}"
                        for evidence in ingredient_evidences
                    ),
                )
            )
        return rows

    def _group_first(self, items, *, key):
        grouped: dict[UUID, object] = {}
        for item in items:
            grouped.setdefault(key(item), item)
        return grouped


async def _run() -> None:
    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            ingredients = await IngredientMasterReader(session).list_all()
            facts = await IngredientKnowledgeFactRepository(session).list_all()
            evidences = await EvidenceRepository(session).list_all()
    finally:
        await database.dispose()

    rows = IngredientDatasetExporter().build_rows(ingredients, facts, evidences)
    IngredientDatasetCsvWriter().write(rows, _OUTPUT_PATH)
    print(
        f"성분 {len(rows)}건 저장 완료: {_OUTPUT_PATH} "
        f"(지식데이터 매칭 {sum(1 for r in rows if r.knowledge_inci_name)}건, "
        f"근거 있는 성분 {sum(1 for r in rows if r.evidence_count > 0)}건)"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run())
