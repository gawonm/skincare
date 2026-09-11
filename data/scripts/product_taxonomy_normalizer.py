"""상품명과 원본 카테고리에서 서비스용 제품 분류를 만든다.

원본 `category1`~`category3`와 쇼핑몰의 `product_type`은 고치지 않는다. 구체적인 상품명
표현을 먼저 판정하고, 근거가 부족하면 억지로 분류하지 않고 NULL로 남긴다.
"""

import html
import re
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from data.scripts.product_candidate_schemas import (
    ProductCandidateRow,
    ProductTypeNormalized,
    ServiceCategory,
)


class TaxonomyDecisionBasis(StrEnum):
    TITLE = "title"
    SOURCE_CATEGORY = "source_category"
    UNCLASSIFIED = "unclassified"


class ProductTaxonomyInput(BaseModel):
    """CSV와 DB 상품이 분류기에 공통으로 넘기는 최소 입력."""

    model_config = ConfigDict(frozen=True)

    raw_title: str
    display_title: str
    category3: str | None = None


class ProductTaxonomyTitleSignal(BaseModel):
    """표시명에서 발견했지만 최종 저장값에는 사용하지 않는 진단 신호."""

    model_config = ConfigDict(frozen=True)

    product_type_normalized: ProductTypeNormalized
    matched_keyword: str


class ProductTaxonomyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_type_normalized: ProductTypeNormalized | None
    service_category: ServiceCategory | None
    basis: TaxonomyDecisionBasis
    matched_keyword: str | None = None
    display_title_signal: ProductTaxonomyTitleSignal | None = None


class ProductTaxonomyRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_type: ProductTypeNormalized
    keywords: tuple[str, ...]
    excluded_keywords: tuple[str, ...] = ()


class ProductTaxonomyNormalizer:
    # sun serum·cleansing balm처럼 용도가 구체적인 표현을 일반 제형보다 먼저 판정한다.
    _RULES: tuple[ProductTaxonomyRule, ...] = (
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.SUNSCREEN,
            keywords=(
                "sunscreen",
                "sun cream",
                "sun stick",
                "sun serum",
                "sun lotion",
                "spf",
                "선크림",
                "선스틱",
            ),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.CLEANSING_FOAM,
            keywords=("cleansing foam", "cleaning foam", "클렌징 폼"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.CLEANSING_GEL,
            keywords=("cleansing gel", "클렌징 젤"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.CLEANSING_OIL,
            keywords=("cleansing oil", "클렌징 오일"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.CLEANSING_BALM,
            keywords=("cleansing balm", "클렌징 밤"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.CLEANSING_WATER,
            keywords=("cleansing water", "micellar water", "클렌징 워터"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.CLEANSER,
            keywords=(
                "cleanser",
                "cleansing",
                "face wash",
                "makeup remover",
                "클렌저",
                "클렌징",
                "세안",
            ),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.SHEET_MASK,
            keywords=("sheet mask", "mask sheet", "마스크 시트", "시트 마스크"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.WASH_OFF_MASK,
            keywords=("wash off mask", "워시오프 마스크"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.SLEEPING_MASK,
            keywords=("sleeping mask", "sleeping pack", "슬리핑 마스크", "슬리핑 팩"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.MASK,
            keywords=("mask", "마스크"),
            excluded_keywords=("mask cream", "mask serum"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.PATCH,
            keywords=("patch", "패치"),
            excluded_keywords=(
                "belly patch",
                "trapezius patch",
                "neck & chin care patch",
                "복부 패치",
                "승모근 패치",
            ),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.TONER_PAD,
            keywords=("toner pad", "toning pad", "토너 패드"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.PEELING,
            keywords=("peeling", "peel", "필링"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.MIST,
            keywords=("mist", "미스트"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.FACIAL_OIL,
            keywords=("face oil", "facial oil", "페이스 오일"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.SPOT_TREATMENT,
            keywords=("spot treatment", "spot care", "스팟 케어"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.BOOSTER,
            keywords=("booster", "부스터"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.ALL_IN_ONE,
            keywords=("all in one", "올인원"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.BALM,
            keywords=("balm", "페이스 밤"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.AMPOULE,
            keywords=("ampoule", "앰플"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.SERUM,
            keywords=("serum", "세럼"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.ESSENCE,
            keywords=("essence", "에센스"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.TONER,
            keywords=("toner", "toning water", "토너"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.EMULSION,
            keywords=("emulsion", "에멀전", "에멀젼"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.LOTION,
            keywords=("lotion", "로션"),
        ),
        ProductTaxonomyRule(
            product_type=ProductTypeNormalized.CREAM,
            keywords=("cream", "크림"),
        ),
    )

    _SERVICE_CATEGORY_BY_TYPE: ClassVar[dict[ProductTypeNormalized, ServiceCategory]] = {
        ProductTypeNormalized.SERUM: ServiceCategory.ESSENCE_SERUM,
        ProductTypeNormalized.ESSENCE: ServiceCategory.ESSENCE_SERUM,
        ProductTypeNormalized.AMPOULE: ServiceCategory.AMPOULE,
        ProductTypeNormalized.CREAM: ServiceCategory.CREAM_LOTION,
        ProductTypeNormalized.LOTION: ServiceCategory.CREAM_LOTION,
        ProductTypeNormalized.EMULSION: ServiceCategory.CREAM_LOTION,
        ProductTypeNormalized.TONER: ServiceCategory.TONER_PAD,
        ProductTypeNormalized.TONER_PAD: ServiceCategory.TONER_PAD,
        ProductTypeNormalized.CLEANSER: ServiceCategory.CLEANSER,
        ProductTypeNormalized.CLEANSING_FOAM: ServiceCategory.CLEANSER,
        ProductTypeNormalized.CLEANSING_GEL: ServiceCategory.CLEANSER,
        ProductTypeNormalized.CLEANSING_OIL: ServiceCategory.CLEANSER,
        ProductTypeNormalized.CLEANSING_BALM: ServiceCategory.CLEANSER,
        ProductTypeNormalized.CLEANSING_WATER: ServiceCategory.CLEANSER,
        ProductTypeNormalized.SHEET_MASK: ServiceCategory.MASK_PATCH,
        ProductTypeNormalized.WASH_OFF_MASK: ServiceCategory.MASK_PATCH,
        ProductTypeNormalized.SLEEPING_MASK: ServiceCategory.MASK_PATCH,
        ProductTypeNormalized.MASK: ServiceCategory.MASK_PATCH,
        ProductTypeNormalized.PATCH: ServiceCategory.MASK_PATCH,
        ProductTypeNormalized.SUNSCREEN: ServiceCategory.SUNCARE,
        ProductTypeNormalized.MIST: ServiceCategory.OTHER,
        ProductTypeNormalized.FACIAL_OIL: ServiceCategory.OTHER,
        ProductTypeNormalized.BALM: ServiceCategory.OTHER,
        ProductTypeNormalized.SPOT_TREATMENT: ServiceCategory.OTHER,
        ProductTypeNormalized.BOOSTER: ServiceCategory.OTHER,
        ProductTypeNormalized.PEELING: ServiceCategory.OTHER,
        ProductTypeNormalized.ALL_IN_ONE: ServiceCategory.OTHER,
    }

    def classify(self, input_: ProductTaxonomyInput) -> ProductTaxonomyResult:
        # 번역 여부가 저장 분류를 바꾸지 않도록 최종 판정에는 수집 원문만 사용한다.
        raw_title_signal = self._title_signal(input_.raw_title)
        display_title_signal = self._display_title_signal(input_)
        if raw_title_signal is not None:
            return self._result(
                product_type=raw_title_signal.product_type_normalized,
                basis=TaxonomyDecisionBasis.TITLE,
                matched_keyword=raw_title_signal.matched_keyword,
                display_title_signal=display_title_signal,
            )

        if self._normalize(input_.category3 or "") == "cleansers":
            return self._result(
                product_type=ProductTypeNormalized.CLEANSER,
                basis=TaxonomyDecisionBasis.SOURCE_CATEGORY,
                matched_keyword=input_.category3 or "",
                display_title_signal=display_title_signal,
            )

        return ProductTaxonomyResult(
            product_type_normalized=None,
            service_category=None,
            basis=TaxonomyDecisionBasis.UNCLASSIFIED,
            display_title_signal=display_title_signal,
        )

    def apply(self, row: ProductCandidateRow) -> ProductCandidateRow:
        result = self.classify(
            ProductTaxonomyInput(
                raw_title=row.raw_title,
                display_title=row.display_title,
                category3=row.category3,
            )
        )
        return row.model_copy(
            update={
                "product_type_normalized": result.product_type_normalized,
                "service_category": result.service_category,
            }
        )

    def service_category(self, product_type: ProductTypeNormalized) -> ServiceCategory:
        return self._SERVICE_CATEGORY_BY_TYPE[product_type]

    def _result(
        self,
        *,
        product_type: ProductTypeNormalized,
        basis: TaxonomyDecisionBasis,
        matched_keyword: str,
        display_title_signal: ProductTaxonomyTitleSignal | None,
    ) -> ProductTaxonomyResult:
        return ProductTaxonomyResult(
            product_type_normalized=product_type,
            service_category=self.service_category(product_type),
            basis=basis,
            matched_keyword=matched_keyword,
            display_title_signal=display_title_signal,
        )

    def _title_signal(self, title: str) -> ProductTaxonomyTitleSignal | None:
        normalized_title = self._normalize(title)
        for rule in self._RULES:
            matched_keyword = self._matches_rule(normalized_title, rule)
            if matched_keyword is not None:
                return ProductTaxonomyTitleSignal(
                    product_type_normalized=rule.product_type,
                    matched_keyword=matched_keyword,
                )
        return None

    def _display_title_signal(
        self,
        input_: ProductTaxonomyInput,
    ) -> ProductTaxonomyTitleSignal | None:
        if self._normalize(input_.display_title) == self._normalize(input_.raw_title):
            return None
        return self._title_signal(input_.display_title)

    def _normalize(self, value: str) -> str:
        unescaped = html.unescape(value).casefold()
        return " ".join(re.sub(r"[^\w가-힣]+", " ", unescaped).split())

    def _contains(self, text: str, keyword: str) -> bool:
        normalized_keyword = self._normalize(keyword)
        return f" {normalized_keyword} " in f" {text} "

    def _matches_rule(self, title: str, rule: ProductTaxonomyRule) -> str | None:
        if any(self._contains(title, keyword) for keyword in rule.excluded_keywords):
            return None
        return next(
            (keyword for keyword in rule.keywords if self._contains(title, keyword)),
            None,
        )
