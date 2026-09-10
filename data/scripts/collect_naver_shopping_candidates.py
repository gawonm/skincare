"""네이버 쇼핑 API로 성분군별 제품 후보를 모아 `data/processed/product_candidates.csv` 에
저장하는 진입점.

사용법:
    uv run python -m data.scripts.collect_naver_shopping_candidates

`NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` 환경변수가 필요하다. `.env` 파일은 docker-compose
전용이라 자동으로 읽지 않으므로, 실행 전 셸에 직접 export 한다.

여기서 만드는 CSV 는 아직 전성분을 검증하지 않은 후보다. 성분군별로 사람이 직접 확인해
`verified_products.csv` 로 옮기기 전까지는 추천에 사용하지 않는다 (`docs/data/data.md` 참고).
"""

from pathlib import Path

from data.scripts.image_downloader import ImageDownloader
from data.scripts.naver_shopping_candidate_builder import ProductCandidateBuilder
from data.scripts.naver_shopping_candidate_collector import ProductCandidateCollector
from data.scripts.naver_shopping_client import NaverShoppingClient, NaverShoppingCredentials
from data.scripts.naver_shopping_title_cleaner import ShoppingTitleCleaner
from data.scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from data.scripts.product_candidate_schemas import TargetGroup
from data.scripts.product_price_band_classifier import PriceBandClassifier
from data.scripts.product_volume_parser import ProductVolumeParser

_OUTPUT_PATH = Path("data/processed/product_candidates.csv")

# 성분군별 검색어. 검색어에 성분명이 들어 있다고 전성분 검증이 끝난 것은 아니다.
TARGET_GROUP_SEARCH_QUERIES: dict[TargetGroup, tuple[str, ...]] = {
    TargetGroup.VITAMIN_C: ("비타민C 세럼", "아스코빅애씨드 세럼"),
    TargetGroup.NIACINAMIDE: ("나이아신아마이드 세럼", "나이아신아마이드 앰플"),
    TargetGroup.RETINOL: ("레티놀 세럼", "레티놀 크림"),
    # "AHA 토너"/"락틱애씨드 세럼"은 뺐다. TargetGroup.AHA 값이 "글라이콜릭애씨드"로
    # 특정 성분을 가리키는데, "AHA 토너"는 락틱애씨드 등 다른 AHA 계열 산까지 섞여
    # 나오고 "락틱애씨드 세럼"은 아예 다른 산이라 이 그룹에 넣으면 성분명이 틀린다.
    TargetGroup.AHA: ("글라이콜릭애씨드 토너", "글라이콜릭애씨드 세럼"),
    TargetGroup.BHA: ("BHA 토너", "살리실릭애씨드 토너", "살리실릭애씨드 세럼"),
}


def main() -> None:
    client = NaverShoppingClient(NaverShoppingCredentials.from_env())
    image_downloader = ImageDownloader()
    try:
        collector = ProductCandidateCollector(
            client=client,
            builder=ProductCandidateBuilder(
                ShoppingTitleCleaner(),
                PriceBandClassifier(),
                image_downloader,
                ProductVolumeParser(),
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
