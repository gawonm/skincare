"""올리브영 전성분 원문(`data/processed/product_candidates.csv`)을 파싱·옵션 연결·표준
성분 매칭까지 끝내 `product_ingredient_snapshot`/`product_ingredient`에 저장하는 진입점.

파싱·옵션 연결(`ProductIngredientTextParser`/`ProductIngredientOptionLinker`)은 올리브영
세션 소유, 매칭·저장(`ProductIngredientService`)은 이 세션 소유 — 두 계약을 여기서 조립한다.
`scripts/inspect_ingredient_parsing.py`(DB에 안 쓰고 리포트만 만드는 버전)와 같은 읽기·
파싱 경로를 쓰되, 여기서는 실제로 DB에 커밋한다.

사용법:
    uv run python -m scripts.ingest_product_ingredients
"""

import asyncio
import csv
from pathlib import Path

from backend.repositories.product_ingredient_repository import ProductIngredientRepository
from backend.services.product_ingredient_service import ProductIngredientService
from core.config import settings
from core.database import Database
from scripts.oliveyoung_global_client import OliveYoungGlobalClient
from scripts.product_candidate_schemas import DataSource
from scripts.product_ingredient_option_linker import ProductIngredientOptionLinker
from scripts.product_ingredient_text_parser import PARSER_VERSION, ProductIngredientTextParser

_CANDIDATES_CSV_PATH = Path("data/processed/product_candidates.csv")


def _read_rows_with_ingredients_text() -> list[dict[str, str]]:
    with _CANDIDATES_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [
            row
            for row in reader
            if row["source"] == DataSource.OLIVEYOUNG_GLOBAL.value and row["raw_ingredients_text"]
        ]


def _dedupe_by_product_id(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    # 상품 식별자는 (source, source_product_id) 조합이다 - `candidate_id`는 재수집마다
    # 바뀔 수 있어 식별자로 안 쓴다. 같은 상품이 여러 target_group 행에 등장해도
    # raw_ingredients_text는 동일해 한 번만 처리한다(inspect_ingredient_parsing.py와 동일 로직).
    seen_product_ids: set[str] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        product_id = row["source_product_id"]
        if product_id in seen_product_ids:
            continue
        seen_product_ids.add(product_id)
        deduped.append(row)
    return deduped


async def _run() -> None:
    parser = ProductIngredientTextParser()
    linker = ProductIngredientOptionLinker()
    client = OliveYoungGlobalClient()

    all_rows = _read_rows_with_ingredients_text()
    rows = _dedupe_by_product_id(all_rows)

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            service = await ProductIngredientService.create(session)

            new_snapshots = 0
            for row in rows:
                result = parser.parse(
                    DataSource.OLIVEYOUNG_GLOBAL,
                    row["source_product_id"],
                    row["raw_ingredients_text"],
                )
                has_option_sections = any(
                    section.section_label is not None for section in result.sections
                )
                if has_option_sections:
                    detail = client.get_product_detail(row["source_product_id"])
                    result = linker.link(result, tuple(detail.option_list))

                ingestion = await service.ingest(
                    DataSource.OLIVEYOUNG_GLOBAL.value, result, PARSER_VERSION
                )
                if ingestion.is_new_snapshot:
                    new_snapshots += 1

            await session.commit()

            counts = await ProductIngredientRepository(session).count_by_match_acceptance()
            print(f"상품 {len(rows)}개(중복 제외) 처리 완료. 새 스냅샷 {new_snapshots}개.")
            print("match_acceptance 집계:", {k.value: v for k, v in counts.items()})
    finally:
        client.close()
        await database.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
