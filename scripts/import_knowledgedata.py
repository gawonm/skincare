"""Knowledgedata.xlsx를 성분명 매칭 후 `IngredientKnowledgeFact`로 적재하는 진입점.

사용법:
    uv run python -m scripts.import_knowledgedata "data/Knowledgedata.xlsx"

먼저 `scripts.import_kcia_ingredients` 로 `IngredientMaster` 를 채워야 한다. 매칭 후보가
없으면 모든 행이 수동 검토 큐로 빠진다.
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import Database
from models.ingredient import IngredientMaster
from scripts.ingredient_name_matcher import IngredientNameMatcher
from scripts.ingredient_name_normalizer import IngredientNameNormalizer
from scripts.ingredient_schemas import IngredientCandidate
from scripts.knowledgedata_importer import KnowledgedataImporter
from scripts.knowledgedata_parser import KnowledgedataParser

_DEFAULT_REVIEW_QUEUE_PATH = Path("data/manual_review/knowledgedata_ingredient_match_queue.csv")


async def _load_candidates(session: AsyncSession) -> list[IngredientCandidate]:
    result = await session.execute(
        select(
            IngredientMaster.id,
            IngredientMaster.standard_name_ko,
            IngredientMaster.standard_name_en,
            IngredientMaster.old_names_ko,
            IngredientMaster.old_names_en,
            IngredientMaster.normalized_name_ko,
            IngredientMaster.normalized_name_en,
        )
    )
    return [
        IngredientCandidate(
            ingredient_id=row.id,
            standard_name_ko=row.standard_name_ko,
            standard_name_en=row.standard_name_en,
            old_names_ko=tuple(row.old_names_ko),
            old_names_en=tuple(row.old_names_en),
            normalized_name_ko=row.normalized_name_ko,
            normalized_name_en=row.normalized_name_en,
        )
        for row in result.all()
    ]


async def _run(xlsx_path: str, review_queue_path: Path) -> None:
    rows = KnowledgedataParser().parse(xlsx_path)
    print(f"Knowledgedata에서 {len(rows)}개 행을 읽었습니다.")

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            candidates = await _load_candidates(session)
            if not candidates:
                raise RuntimeError(
                    "IngredientMaster가 비어 있습니다. "
                    "scripts.import_kcia_ingredients 를 먼저 실행하세요."
                )
            matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
            importer = KnowledgedataImporter(session, matcher, review_queue_path)
            summary = await importer.import_rows(rows)
            await session.commit()
    finally:
        await database.dispose()

    print(
        f"적재 완료: 총 {summary.total_rows}건 "
        f"(매칭 {summary.matched}건, 수동 검토 {summary.manual_review}건)"
    )
    if summary.manual_review:
        print(f"수동 검토 대상은 {review_queue_path} 에 저장했습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx_path", help="Knowledgedata.xlsx 경로")
    parser.add_argument(
        "--review-queue-path",
        type=Path,
        default=_DEFAULT_REVIEW_QUEUE_PATH,
        help=f"수동 검토 큐 CSV 경로 (기본값: {_DEFAULT_REVIEW_QUEUE_PATH})",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.xlsx_path, args.review_queue_path))


if __name__ == "__main__":
    main()
