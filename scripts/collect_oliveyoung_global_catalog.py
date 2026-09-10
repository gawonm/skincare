"""올리브영 글로벌 Skincare 카테고리 전체를 순회해 `data/processed/catalog_products.csv`
에 저장하는 진입점.

성분 키워드 검색으로 모은 `data/processed/product_candidates.csv`는 건드리지 않는다 —
별도 산출물이다(`docs/oliveyoung_global_pipeline_handoff.md` 참고).

재실행하면 이 CSV에 이미 있는 상품은 다시 상세·전성분을 부르지 않고 건너뛴다. 즉
재실행 자체가 중단 지점 이후 재개다 — 별도 `--resume` 플래그가 없다.

사용법:
    uv run python -m scripts.collect_oliveyoung_global_catalog
    uv run python -m scripts.collect_oliveyoung_global_catalog --max-new-products 20  # 검증용 소규모 실행
"""

import argparse
from pathlib import Path

from scripts.catalog_eligibility_policy import CatalogEligibilityPolicy
from scripts.image_downloader import ImageDownloader
from scripts.oliveyoung_global_catalog_crawler import OliveYoungGlobalCatalogCrawler
from scripts.oliveyoung_global_category_client import OliveYoungGlobalCategoryClient
from scripts.oliveyoung_global_client import OliveYoungGlobalClient
from scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from scripts.product_candidate_schemas import DataSource
from scripts.product_price_band_classifier import PriceBandClassifier
from scripts.product_title_translator import ProductTitleTranslator
from scripts.product_volume_parser import ProductVolumeParser

_OUTPUT_PATH = Path("data/processed/catalog_products.csv")


def _parse_max_new_products() -> int | None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-new-products",
        type=int,
        default=None,
        help="이번 실행에서 새로 상세 조회할 상품 수 상한 (소규모 검증용)",
    )
    return parser.parse_args().max_new_products


def main() -> None:
    max_new_products = _parse_max_new_products()

    writer = ProductCandidateCsvWriter()
    existing_rows = writer.read_existing_rows(_OUTPUT_PATH)
    existing_product_ids = {
        row.source_product_id for row in existing_rows if row.source == DataSource.OLIVEYOUNG_GLOBAL
    }

    # 실행이 수십 분~수 시간 걸릴 수 있어, 끝까지 기다렸다 한 번에 쓰지 않고 상품을
    # 하나 처리할 때마다 즉시 CSV에 반영한다 — 중간에 죽어도 그때까지 결과는 남는다.
    collected_rows: list = []

    def _persist_incrementally(row) -> None:
        collected_rows.append(row)
        writer.write(list(existing_rows) + collected_rows, _OUTPUT_PATH)

    category_client = OliveYoungGlobalCategoryClient()
    product_client = OliveYoungGlobalClient()
    image_downloader = ImageDownloader()
    try:
        crawler = OliveYoungGlobalCatalogCrawler(
            category_client=category_client,
            product_client=product_client,
            eligibility_policy=CatalogEligibilityPolicy(),
            price_band_classifier=PriceBandClassifier(),
            image_downloader=image_downloader,
            title_translator=ProductTitleTranslator(),
            volume_parser=ProductVolumeParser(),
            existing_product_ids=existing_product_ids,
            max_new_products=max_new_products,
            on_row_collected=_persist_incrementally,
        )
        new_rows, report = crawler.run()
    finally:
        category_client.close()
        product_client.close()
        image_downloader.close()

    # 크롤러가 끝까지 정상 완료됐을 때만 이 최종 write가 의미 있다 - 중간에 죽었다면
    # 위 _persist_incrementally가 이미 마지막으로 처리한 상품까지 저장해 뒀다.
    writer.write(list(existing_rows) + new_rows, _OUTPUT_PATH)

    print(f"신규 {len(new_rows)}개 저장 (기존 {len(existing_rows)}개 유지): {_OUTPUT_PATH}")
    print(report.model_dump())
    # max_new_products로 일찍 끊은 소규모 실행이 아니라면, 발견한 모든 상품이
    # 수집/기존/제외/실패 중 어딘가로 집계돼야 한다 — 안 맞으면 어딘가서 조용히 빠뜨린 것.
    if max_new_products is None and report.accounted_total() != report.total_found:
        print(
            f"경고: 집계 불일치 (발견 {report.total_found} != 집계 {report.accounted_total()}). "
            "실행 중 카테고리 목록이 바뀌었을 수 있습니다."
        )


if __name__ == "__main__":
    main()
