"""`product_candidates.csv` + `catalog_products.csv`를 읽어 `product` 테이블을
`(source, source_product_id)` 기준 최신 상태로 맞추는 진입점.

두 CSV에 같은 상품이 둘 다 있으면 `product_candidates.csv`(성분 키워드 검색 결과,
`target_group`이 채워짐) 쪽을 우선한다 - `catalog_products.csv`(카테고리 전수 크롤링)는
`target_group`이 항상 NULL이라, 순서를 반대로 하면 이미 알고 있는 성분군 정보가
사라진다. `data/scripts/ingest_product_ingredients.py`와 같은 순서(후보 CSV 먼저)를 쓴다.

사용법:
    uv run python -m data.scripts.ingest_product_catalog

`backend.services.product_service.ProductService`가 아직 없으면 이 스크립트는 import
단계에서 실패한다 - backend 파트가 `docs/contracts/data-to-backend.md`대로 구현할 때까지
대기 중인 상태다. data 세션이 검증까지 마친 참고 구현이 그 계약 문서에 있다.
"""

import asyncio
from pathlib import Path

from backend.services.product_service import ProductService

from core.config import settings
from core.database import Database
from data.scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from data.scripts.product_candidate_schemas import ProductCandidateRow

_CANDIDATES_CSV_PATH = Path("data/processed/product_candidates.csv")
_CATALOG_CSV_PATH = Path("data/processed/catalog_products.csv")


def _read_rows(csv_path: Path) -> list[ProductCandidateRow]:
    if not csv_path.exists():
        return []
    return ProductCandidateCsvWriter().read_existing_rows(csv_path)


def _dedupe_by_product_id(rows: list[ProductCandidateRow]) -> list[ProductCandidateRow]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ProductCandidateRow] = []
    for row in rows:
        key = (row.source.value, row.source_product_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


async def _run() -> None:
    rows = _dedupe_by_product_id(_read_rows(_CANDIDATES_CSV_PATH) + _read_rows(_CATALOG_CSV_PATH))

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            service = ProductService(session)

            created = 0
            updated = 0
            for row in rows:
                _, is_new = await service.ingest(row)
                if is_new:
                    created += 1
                else:
                    updated += 1

            await session.commit()
            print(f"상품 {len(rows)}개(중복 제외) 처리 완료. 신규 {created}개 / 갱신 {updated}개.")
    finally:
        await database.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
