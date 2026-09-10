"""`NaverShoppingItem` 하나를 `ProductCandidateRow` 로 변환한다."""

from datetime import datetime

from data.scripts.image_downloader import ImageDownloader
from data.scripts.naver_shopping_schemas import NaverShoppingItem
from data.scripts.naver_shopping_title_cleaner import ShoppingTitleCleaner
from data.scripts.product_candidate_schemas import (
    DataSource,
    MatchStatus,
    ProductCandidateRow,
    TargetGroup,
    TitleSource,
)
from data.scripts.product_price_band_classifier import PriceBandClassifier
from data.scripts.product_volume_parser import ProductVolumeParser


class ProductCandidateBuilder:
    """유효하지 않은 항목(가격 0원, 상품 ID 없음)은 `None` 을 반환해 걸러낸다."""

    def __init__(
        self,
        title_cleaner: ShoppingTitleCleaner,
        price_band_classifier: PriceBandClassifier,
        image_downloader: ImageDownloader,
        volume_parser: ProductVolumeParser,
    ) -> None:
        self._title_cleaner = title_cleaner
        self._price_band_classifier = price_band_classifier
        self._image_downloader = image_downloader
        self._volume_parser = volume_parser

    def build(
        self,
        *,
        candidate_id: str,
        target_group: TargetGroup,
        search_query: str,
        item: NaverShoppingItem,
        observed_at: datetime,
    ) -> ProductCandidateRow | None:
        if not item.product_id:
            return None

        lowest_price = int(item.lprice) if item.lprice else 0
        if lowest_price <= 0:
            return None

        local_image_path = self._image_downloader.download(
            item.image, file_stem=f"{DataSource.NAVER_SHOPPING.value}_{item.product_id}"
        )
        # 네이버 쇼핑은 한국 쇼핑 검색이라 title 이 이미 한글이다. 번역할 게 없다.
        cleaned_title = self._title_cleaner.clean(item.title)
        volume_value, volume_unit = self._volume_parser.parse(cleaned_title)

        return ProductCandidateRow(
            candidate_id=candidate_id,
            source=DataSource.NAVER_SHOPPING,
            target_group=target_group,
            search_query=search_query,
            source_product_id=item.product_id,
            raw_title=cleaned_title,
            display_title=cleaned_title,
            title_source=TitleSource.NATIVE_KR,
            brand=item.brand,
            maker=item.maker,
            category1=item.category1,
            category2=item.category2,
            category3=item.category3,
            lowest_price=lowest_price,
            highest_price=int(item.hprice) if item.hprice else 0,
            price_band=self._price_band_classifier.classify(lowest_price),
            volume_value=volume_value,
            volume_unit=volume_unit,
            image_url=item.image,
            local_image_path=str(local_image_path),
            shopping_url=item.link,
            mall_name=item.mall_name,
            product_type=item.product_type,
            observed_at=observed_at,
            match_status=MatchStatus.MANUAL_REVIEW_REQUIRED,
        )
