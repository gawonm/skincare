"""MFDS 화장품 사용제한 원료정보를 전량 수집해 `Evidence`로 적재하는 진입점.

사용법:
    uv run python -m data.scripts.import_mfds_restricted_ingredients

`config.yaml`의 `mfds.service_key`가 필요하다. 이 API는 성분명 필터가 없어 전체
(약 3만여 건)를 페이지네이션으로 순회하므로 시간이 걸린다.
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import Database
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.ingredient_schemas import IngredientCandidate
from data.scripts.mfds_client import MfdsRestrictedIngredientClient
from data.scripts.mfds_importer import MfdsRestrictedIngredientImporter
from models.ingredient import IngredientMaster

_DEFAULT_REVIEW_QUEUE_PATH = Path("data/manual_review/mfds_ingredient_match_queue.csv")


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


async def _run(review_queue_path: Path) -> None:
    if settings.mfds is None:
        raise RuntimeError(
            "config.yaml에 mfds.service_key가 없습니다. config.yaml.sample을 참고해 추가하세요."
        )

    client = MfdsRestrictedIngredientClient(settings.mfds)
    try:
        print("MFDS API에서 화장품 사용제한 원료정보를 수집하는 중...")
        items = await client.fetch_all()
    finally:
        await client.close()
    print(f"MFDS API에서 {len(items)}건을 받았습니다.")

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            candidates = await _load_candidates(session)
            if not candidates:
                raise RuntimeError(
                    "IngredientMaster가 비어 있습니다. "
                    "data.scripts.import_kcia_ingredients 를 먼저 실행하세요."
                )
            matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
            importer = MfdsRestrictedIngredientImporter(session, matcher, review_queue_path)
            summary = await importer.import_items(items)
            await session.commit()
    finally:
        await database.dispose()

    print(
        f"적재 완료: 총 {summary.total_items}건 "
        f"(매칭 {summary.inserted}건, 수동 검토 {summary.manual_review}건)"
    )
    if summary.manual_review:
        print(f"수동 검토 대상은 {review_queue_path} 에 저장했습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-queue-path",
        type=Path,
        default=_DEFAULT_REVIEW_QUEUE_PATH,
        help=f"수동 검토 큐 CSV 경로 (기본값: {_DEFAULT_REVIEW_QUEUE_PATH})",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.review_queue_path))


if __name__ == "__main__":
    main()
