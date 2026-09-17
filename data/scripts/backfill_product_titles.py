"""`data/manual_review/product_title_translations_final.csv`(raw_title -> display_title
매핑)를 `product_candidates.csv` + `catalog_products.csv`의 현재 상품 스냅샷과
`(source, source_product_id)` 자연키로 연결해 `product.display_title`/`title_source`만
갱신한다.

`ingest_product_catalog.py`와 같은 순서로 두 CSV를 합친다(후보 CSV 먼저, dedupe) —
같은 상품이 두 CSV에 모두 있으면 후보 CSV 쪽 행이 우선이라, source_product_id는
후보 쪽 값을 쓴다.

매핑은 raw_title 기준이지만 DB 갱신은 자연키(source, source_product_id) 기준이어야
하므로, 상품마다 raw_title로 매핑을 찾은 뒤 그 상품의 natural key로 갱신한다.

기본 동작은 review_status == accepted 인 매핑만 반영한다(needs_review는 skip).
`ProductService.ingest`를 재호출하지 않는다 — 가격/이미지/URL/카테고리 등 20+ 필드를
덮어쓸 위험이 있어, `ProductService.update_title`(두 필드 전용)만 사용한다.

사용법:
    uv run python -m data.scripts.backfill_product_titles --dry-run
    uv run python -m data.scripts.backfill_product_titles
"""

import argparse
import asyncio
from pathlib import Path

import csv as csv_module

from backend.repositories.product_repository import ProductRepository, ProductTitleUpdate
from core.config import settings
from core.database import Database
from data.scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from data.scripts.product_candidate_schemas import ProductCandidateRow
from models.product import ProductTitleSource

_CANDIDATES_CSV_PATH = Path("data/processed/product_candidates.csv")
_CATALOG_CSV_PATH = Path("data/processed/catalog_products.csv")
_FINAL_MAPPING_CSV_PATH = Path("data/manual_review/product_title_translations_final.csv")

# 매핑 파일의 localization_source -> DB의 title_source. 국내 공식 소스로 확인된 것만
# OLIVEYOUNG_KR로 승격하고, 나머지(사전/규칙 번역, 기존 수동 매핑, 리뷰 경로)는 전부
# "번역됨(공식명 아님)"인 TRANSLATED로 묶는다 — TitleSource 자체가 이 두 단계만 신뢰도로
# 구분하도록 설계돼 있다(models/product.py의 ProductTitleSource 주석 참고).
_LOCALIZATION_SOURCE_TO_TITLE_SOURCE: dict[str, ProductTitleSource] = {
    "oliveyoung_kr": ProductTitleSource.OLIVEYOUNG_KR,
    "brand_official_kr": ProductTitleSource.OLIVEYOUNG_KR,
    "existing_manual": ProductTitleSource.TRANSLATED,
    "rule_translated": ProductTitleSource.TRANSLATED,
    "dictionary_fix": ProductTitleSource.TRANSLATED,
    "manual_review": ProductTitleSource.TRANSLATED,
    "unresolved": ProductTitleSource.TRANSLATED,
}


def _read_candidate_rows(csv_path: Path) -> list[ProductCandidateRow]:
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


def _read_mapping(csv_path: Path) -> dict[str, dict[str, str]]:
    with open(csv_path, encoding="utf-8", newline="") as f:
        return {row["raw_title"]: row for row in csv_module.DictReader(f)}


async def _run(dry_run: bool) -> None:
    products = _dedupe_by_product_id(
        _read_candidate_rows(_CANDIDATES_CSV_PATH) + _read_candidate_rows(_CATALOG_CSV_PATH)
    )
    mapping = _read_mapping(_FINAL_MAPPING_CSV_PATH)

    product_titles = {p.raw_title for p in products}
    stale_mappings = sum(1 for raw_title in mapping if raw_title not in product_titles)

    total_products = len(products)
    accepted_matched = 0
    needs_review_skipped = 0
    no_mapping = 0
    would_update = 0
    unchanged = 0
    failed = 0

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            repository = ProductRepository(session)

            for product in products:
                mapped = mapping.get(product.raw_title)
                if mapped is None:
                    no_mapping += 1
                    continue

                if mapped["review_status"] != "accepted":
                    needs_review_skipped += 1
                    continue

                accepted_matched += 1

                target_title_source = _LOCALIZATION_SOURCE_TO_TITLE_SOURCE.get(
                    mapped["localization_source"], ProductTitleSource.TRANSLATED
                )
                target_display_title = mapped["display_title"]

                existing = await repository.find(product.source.value, product.source_product_id)
                if existing is None:
                    # candidate/catalog CSV에는 있지만 DB에는 아직 없는 상품 -> update 대상 아님
                    # (title-only 백필이지 신규 적재가 아니다).
                    failed += 1
                    continue

                if (
                    existing.display_title == target_display_title
                    and existing.title_source == target_title_source
                ):
                    unchanged += 1
                    continue

                would_update += 1

                if not dry_run:
                    await repository.update_title(
                        ProductTitleUpdate(
                            source=product.source.value,
                            source_product_id=product.source_product_id,
                            display_title=target_display_title,
                            title_source=target_title_source,
                        )
                    )

            if dry_run:
                # SELECT만 수행했으므로 커밋 없이 세션을 그대로 버린다 -> DB 상태 불변 보장.
                await session.rollback()
            else:
                await session.commit()
    finally:
        await database.dispose()

    print(f"total products: {total_products}")
    print(f"accepted mapping matched: {accepted_matched}")
    print(f"needs_review skipped: {needs_review_skipped}")
    print(f"no mapping: {no_mapping}")
    print(f"stale mappings: {stale_mappings}")
    print(f"would update: {would_update}")
    print(f"unchanged: {unchanged}")
    print(f"failed: {failed}")
    print(f"mode: {'dry-run (DB 변경 없음)' if dry_run else 'write'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="product_title_translations_final.csv를 DB의 product.display_title/"
        "title_source에 백필한다 (accepted 매핑만, 기본값)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB에 쓰지 않고 total/matched/would-update/unchanged/failed 집계만 출력한다.",
    )
    args = parser.parse_args()
    asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
