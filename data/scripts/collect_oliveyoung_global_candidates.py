"""올리브영 글로벌 검색으로 성분군별 제품 후보를 모아 `data/processed/product_candidates.csv`
에 저장하는 진입점.

네이버 쇼핑 수집기(`collect_naver_shopping_candidates.py`)와 같은 CSV 를 쓴다. 저장할 때
올리브영 글로벌 소스에 해당하는 행만 교체하고, 다른 소스가 이미 써 놓은 행은 보존한다
(`ProductCandidateCsvWriter` 참고).

이 사이트는 원화를 지원하지 않아 가격은 환율 변환을 거친 KRW 값이다 — 정확한 실시간
환율이 필요하면 `ExchangeRateClient` 가 쓰는 API(Frankfurter, 평일 ECB 환율 기준)를 바꿔야
한다.

사용법:
    uv run python -m data.scripts.collect_oliveyoung_global_candidates

여기서 만드는 CSV 는 아직 전성분을 검증하지 않은 후보다. 성분군별로 사람이 직접 확인해
`verified_products.csv` 로 옮기기 전까지는 추천에 사용하지 않는다 (`docs/data.md` 참고).
"""

from pathlib import Path

from data.scripts.image_downloader import ImageDownloader
from data.scripts.oliveyoung_global_candidate_builder import OliveYoungGlobalCandidateBuilder
from data.scripts.oliveyoung_global_candidate_collector import OliveYoungGlobalCandidateCollector
from data.scripts.oliveyoung_global_client import OliveYoungGlobalClient
from data.scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from data.scripts.product_candidate_schemas import TargetGroup
from data.scripts.product_option_matcher import ProductOptionMatcher
from data.scripts.product_price_band_classifier import PriceBandClassifier
from data.scripts.product_title_translator import ProductTitleTranslator
from data.scripts.product_volume_parser import ProductVolumeParser
from data.scripts.review_reason_overrides import ReviewReasonOverrides

_OUTPUT_PATH = Path("data/processed/product_candidates.csv")

# 성분군별 검색어. 올리브영 글로벌은 영어 사이트라 네이버 수집기와 달리 영어 검색어를
# 쓴다. 검색어에 성분명이 들어 있다고 전성분 검증이 끝난 것은 아니다.
TARGET_GROUP_SEARCH_QUERIES: dict[TargetGroup, tuple[str, ...]] = {
    TargetGroup.VITAMIN_C: ("vitamin c serum", "ascorbic acid serum"),
    TargetGroup.NIACINAMIDE: ("niacinamide serum", "niacinamide ampoule"),
    TargetGroup.RETINOL: ("retinol serum", "retinol cream"),
    # "aha toner"/"lactic acid serum" 은 뺐다. TargetGroup.AHA 값이 "글라이콜릭애씨드"로
    # 특정 성분을 가리키는데, "aha toner"는 락틱애씨드 등 다른 AHA 계열 산까지 섞여
    # 나오고 "lactic acid serum"은 아예 다른 산이라 이 그룹에 넣으면 성분명이 틀린다.
    TargetGroup.AHA: ("glycolic acid toner", "glycolic acid serum"),
    TargetGroup.BHA: ("bha toner", "salicylic acid toner", "salicylic acid serum"),
}


def main() -> None:
    client = OliveYoungGlobalClient()
    image_downloader = ImageDownloader()
    try:
        collector = OliveYoungGlobalCandidateCollector(
            client=client,
            builder=OliveYoungGlobalCandidateBuilder(
                PriceBandClassifier(),
                image_downloader,
                ProductTitleTranslator(),
                ProductVolumeParser(),
                ReviewReasonOverrides(),
                ProductOptionMatcher(),
            ),
            search_queries=TARGET_GROUP_SEARCH_QUERIES,
        )
        rows = collector.collect()
    finally:
        client.close()
        image_downloader.close()

    ProductCandidateCsvWriter().write(rows, _OUTPUT_PATH)
    print(f"{len(rows)}개 후보 저장: {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
