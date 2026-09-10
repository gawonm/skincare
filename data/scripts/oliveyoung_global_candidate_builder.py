"""올리브영 글로벌 검색/상세 결과를 `ProductCandidateRow` 로 변환한다.

가격은 정가(`normal_amount_krw`)를 `highest_price`, 할인가(`sale_amount_krw`)를
`lowest_price` 에 담는다 — `product_candidate_schemas.ProductCandidateRow` 문서 참고.
"""

import html
from datetime import datetime

from data.scripts.image_downloader import ImageDownloader
from data.scripts.oliveyoung_global_schemas import OliveYoungGlobalProductDetail
from data.scripts.product_candidate_schemas import (
    DataSource,
    MatchStatus,
    ProductCandidateRow,
    ReviewReason,
    TargetGroup,
)
from data.scripts.product_option_matcher import ProductOptionMatcher
from data.scripts.product_price_band_classifier import PriceBandClassifier
from data.scripts.product_title_translator import ProductTitleTranslator
from data.scripts.product_volume_parser import ProductVolumeParser
from data.scripts.review_reason_overrides import ReviewReasonOverrides

_IMAGE_CDN_BASE_URL = "https://cdn-image.oliveyoung.com/"
_PRODUCT_DETAIL_URL_TEMPLATE = "https://global.oliveyoung.com/product/detail?prdtNo={prdt_no}"
_MALL_NAME = "OLIVE YOUNG Global"
_CATEGORY_PATH_SEPARATOR = ">"
_CATEGORY_PATH_MAX_PARTS = 3
# detail-data 응답에는 상품 유형 필드가 없다. 검색 API 응답에서는 지금까지 관찰된 모든
# 상품이 "GENERAL_PRODUCT" 였으므로 고정값으로 둔다. 다른 값이 나오면(예: 세트 상품
# 전용 타입) 여기를 고쳐야 한다.
_PRODUCT_TYPE = "GENERAL_PRODUCT"
# 옵션이 이 개수를 넘으면(즉 2개 이상) 대표 옵션 하나만 골랐다는 뜻이라
# ReviewReason.OPTION_AMBIGUOUS 를 붙인다.
_SINGLE_OPTION_COUNT = 1


class OliveYoungGlobalCandidateBuilder:
    def __init__(
        self,
        price_band_classifier: PriceBandClassifier,
        image_downloader: ImageDownloader,
        title_translator: ProductTitleTranslator,
        volume_parser: ProductVolumeParser,
        review_reason_overrides: ReviewReasonOverrides,
        option_matcher: ProductOptionMatcher,
    ) -> None:
        self._price_band_classifier = price_band_classifier
        self._image_downloader = image_downloader
        self._title_translator = title_translator
        self._volume_parser = volume_parser
        self._review_reason_overrides = review_reason_overrides
        self._option_matcher = option_matcher

    def build(
        self,
        *,
        candidate_id: str,
        target_group: TargetGroup,
        search_query: str,
        detail: OliveYoungGlobalProductDetail,
        raw_ingredients_text: str | None,
        observed_at: datetime,
    ) -> ProductCandidateRow:
        category1, category2, category3 = self._split_category_path(detail.category_path_en)

        review_reasons = list(self._review_reason_overrides.get(detail.prdt_no))
        matched_option = None
        if len(detail.option_list) > _SINGLE_OPTION_COUNT:
            matched_option = self._option_matcher.find_matching_option(
                target_group, detail.option_list
            )
            if matched_option is None:
                # 옵션명에서 target_group 성분을 특정할 수 없었다 — 어쩔 수 없이
                # 대표 옵션(상품 레벨 필드) 값을 쓰고, 검토가 필요하다고 표시한다.
                review_reasons.append(ReviewReason.OPTION_AMBIGUOUS)

        if matched_option is not None:
            # 대표 옵션이 아니라 target_group 성분과 실제로 일치하는 옵션을 찾았다.
            # 브랜드명이 옵션명에 안 들어 있어서 붙여야 다른 상품명과 형식이 맞는다.
            raw_title = html.unescape(f"{detail.brand_name} {matched_option.option_name}")
            normal_amount_krw = matched_option.normal_amount_krw
            sale_amount_krw = matched_option.sale_amount_krw
        else:
            raw_title = html.unescape(detail.product_name)
            normal_amount_krw = detail.normal_amount_krw
            sale_amount_krw = detail.sale_amount_krw

        # 판매처가 하나뿐이라 최저/최고가 대신 할인가/정가를 담는다. 정가가 없으면(할인
        # 중이 아니면) 할인가와 정가가 같다.
        lowest_price = sale_amount_krw

        image_url = _IMAGE_CDN_BASE_URL + detail.image_path
        local_image_path = self._image_downloader.download(
            image_url, file_stem=f"{DataSource.OLIVEYOUNG_GLOBAL.value}_{detail.prdt_no}"
        )

        display_title, title_source = self._title_translator.translate(raw_title)
        volume_value, volume_unit = self._volume_parser.parse(raw_title)

        return ProductCandidateRow(
            candidate_id=candidate_id,
            source=DataSource.OLIVEYOUNG_GLOBAL,
            target_group=target_group,
            search_query=search_query,
            source_product_id=detail.prdt_no,
            raw_title=raw_title,
            display_title=display_title,
            title_source=title_source,
            brand=detail.brand_name,
            maker="",
            category1=category1,
            category2=category2,
            category3=category3,
            lowest_price=lowest_price,
            highest_price=normal_amount_krw,
            price_band=self._price_band_classifier.classify(lowest_price),
            volume_value=volume_value,
            volume_unit=volume_unit,
            image_url=image_url,
            local_image_path=str(local_image_path),
            raw_ingredients_text=raw_ingredients_text,
            shopping_url=_PRODUCT_DETAIL_URL_TEMPLATE.format(prdt_no=detail.prdt_no),
            mall_name=_MALL_NAME,
            product_type=_PRODUCT_TYPE,
            observed_at=observed_at,
            match_status=MatchStatus.MANUAL_REVIEW_REQUIRED,
            review_reasons=tuple(review_reasons),
        )

    def _split_category_path(self, category_path_en: str) -> tuple[str, str, str]:
        # allPathCtgrNameEn 은 HTML 엔티티(`&gt;`)로 이어진 문자열이다. 3단계보다 얕으면
        # 남는 칸은 빈 문자열로 둔다.
        parts = [
            part.strip() for part in html.unescape(category_path_en).split(_CATEGORY_PATH_SEPARATOR)
        ]
        padded_parts = parts + [""] * (_CATEGORY_PATH_MAX_PARTS - len(parts))
        category1, category2, category3 = padded_parts[:_CATEGORY_PATH_MAX_PARTS]
        return category1, category2, category3
