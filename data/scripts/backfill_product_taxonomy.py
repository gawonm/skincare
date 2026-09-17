"""`product_candidates.csv` + `catalog_products.csv`를 다시 분류해 이미 적재된 `product`의
분류 두 필드만 갱신한다.

`ingest_product_catalog.py`와 같은 순서로 두 CSV를 합친다 - candidates(성분 키워드 검색,
`target_group`이 채워짐) 먼저, catalog(카테고리 전수 크롤링) 나중에 이어붙이고
`(source, source_product_id)` 기준으로 dedupe하면 먼저 나온 candidates 쪽이 우선한다.
DB의 `product`는 두 CSV 합산 기준으로 존재하므로, catalog만 읽으면 candidates에만 있는
상품이 백필 대상에서 빠진다.

상품명·가격·관측 시각 등은 다시 적재하지 않는다 - `ProductTaxonomyNormalizer.apply()`로
분류만 다시 계산하고, `backend.services.product_service.ProductService.update_taxonomy()`를
그대로 재사용해 DB에 반영한다 (`docs/contracts/data-to-backend.md` 참고). DB write 로직은
새로 만들지 않는다.

사용법:
    uv run python -m data.scripts.backfill_product_taxonomy --dry-run
    uv run python -m data.scripts.backfill_product_taxonomy
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import func, select

from backend.repositories.product_repository import ProductRepository
from backend.services.product_service import ProductService
from core.config import settings
from core.database import Database
from data.scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from data.scripts.product_candidate_schemas import ProductCandidateRow
from data.scripts.product_taxonomy_normalizer import ProductTaxonomyNormalizer
from models.product import Product, ProductServiceCategory, ProductTypeNormalized

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


def _to_model_type(value: ProductTypeNormalized | None) -> "ProductTypeNormalized | None":
    return ProductTypeNormalized(value.value) if value else None


def _to_model_category(value: ProductServiceCategory | None) -> "ProductServiceCategory | None":
    return ProductServiceCategory(value.value) if value else None


class BackfillResult:
    def __init__(self) -> None:
        self.candidates_rows = 0
        self.catalog_rows = 0
        self.merged_unique = 0
        self.total = 0
        self.classified = 0
        self.unclassified = 0
        self.updated = 0
        self.unchanged = 0
        self.failed = 0
        self.db_taxonomy_classified_after: int | None = None
        self.db_taxonomy_total_after: int | None = None
        self.failures: list[str] = []

    def report(self) -> str:
        lines = [
            f"candidates_rows: {self.candidates_rows}",
            f"catalog_rows: {self.catalog_rows}",
            f"merged_unique: {self.merged_unique}",
            f"total: {self.total}",
            f"classified: {self.classified}",
            f"unclassified: {self.unclassified}",
            f"updated: {self.updated}",
            f"unchanged: {self.unchanged}",
            f"failed: {self.failed}",
        ]
        if self.db_taxonomy_total_after is not None:
            lines.append(
                "db_taxonomy_after_dry_run: "
                f"{self.db_taxonomy_classified_after}/{self.db_taxonomy_total_after}"
            )
        if self.failures:
            lines.append("failures:")
            lines.extend(f"  - {failure}" for failure in self.failures)
        return "\n".join(lines)


async def _run(*, dry_run: bool) -> BackfillResult:
    normalizer = ProductTaxonomyNormalizer()
    candidates_rows = _read_rows(_CANDIDATES_CSV_PATH)
    catalog_rows = _read_rows(_CATALOG_CSV_PATH)
    rows = _dedupe_by_product_id(candidates_rows + catalog_rows)

    result = BackfillResult()
    result.candidates_rows = len(candidates_rows)
    result.catalog_rows = len(catalog_rows)
    result.merged_unique = len(rows)
    result.total = len(rows)

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            repository = ProductRepository(session)
            service = ProductService(session)

            for row in rows:
                classified_row = normalizer.apply(row)
                if classified_row.product_type_normalized is not None:
                    result.classified += 1
                else:
                    result.unclassified += 1

                existing = await repository.find(row.source.value, row.source_product_id)
                if existing is None:
                    result.failed += 1
                    result.failures.append(
                        f"{row.source.value}/{row.source_product_id}: DB에 없는 상품"
                    )
                    continue

                before_type = existing.product_type_normalized
                before_category = existing.service_category

                try:
                    await service.update_taxonomy(classified_row)
                except LookupError as error:
                    result.failed += 1
                    result.failures.append(f"{row.source.value}/{row.source_product_id}: {error}")
                    continue

                after_type = _to_model_type(classified_row.product_type_normalized)
                after_category = _to_model_category(classified_row.service_category)
                if before_type == after_type and before_category == after_category:
                    result.unchanged += 1
                else:
                    result.updated += 1

            if dry_run:
                await session.rollback()
            else:
                await session.commit()

            result.db_taxonomy_total_after = await session.scalar(
                select(func.count()).select_from(Product)
            )
            result.db_taxonomy_classified_after = await session.scalar(
                select(func.count())
                .select_from(Product)
                .where(Product.product_type_normalized.is_not(None))
            )
    finally:
        await database.dispose()

    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB write(commit) 없이 분류 결과와 예상 변경 건수만 출력한다.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = asyncio.run(_run(dry_run=args.dry_run))
    print(result.report())


if __name__ == "__main__":
    main()
