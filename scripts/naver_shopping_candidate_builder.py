"""`NaverShoppingItem` 하나를 `ProductCandidateRow` 로 변환한다."""

from datetime import datetime

from scripts.naver_shopping_price_band_classifier import PriceBandClassifier
from scripts.naver_shopping_schemas import (
    MatchStatus,
    NaverShoppingItem,
    ProductCandidateRow,
    TargetGroup,
)
from scripts.naver_shopping_title_cleaner import ShoppingTitleCleaner


class ProductCandidateBuilder:
    """유효하지 않은 항목(가격 0원, 상품 ID 없음)은 `None` 을 반환해 걸러낸다."""

    def __init__(
        self, title_cleaner: ShoppingTitleCleaner, price_band_classifier: PriceBandClassifier
    ) -> None:
        self._title_cleaner = title_cleaner
        self._price_band_classifier = price_band_classifier

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

        return ProductCandidateRow(
            candidate_id=candidate_id,
            target_group=target_group,
            search_query=search_query,
            naver_product_id=item.product_id,
            raw_title=self._title_cleaner.clean(item.title),
            brand=item.brand,
            maker=item.maker,
            category1=item.category1,
            category2=item.category2,
            category3=item.category3,
            lowest_price=lowest_price,
            highest_price=int(item.hprice) if item.hprice else 0,
            price_band=self._price_band_classifier.classify(lowest_price),
            image_url=item.image,
            shopping_url=item.link,
            mall_name=item.mall_name,
            product_type=item.product_type,
            observed_at=observed_at,
            match_status=MatchStatus.MANUAL_REVIEW_REQUIRED,
        )
