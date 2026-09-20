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


class ProductTaxonomyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_type_normalized: ProductTypeNormalized | None
    service_category: ServiceCategory | None
    basis: TaxonomyDecisionBasis
    matched_keyword: str | None = None


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
            keywords=("ampoule", "ampule", "앰플"),
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

    # 앰플·세럼·에센스는 제품명 앞쪽에 수식어로 자주 붙는다("Ampoule Toner", "Essence Cream").
    # 그래서 이 세 유형과 아래 최종 형태 키워드가 함께 나오면, 최종 형태 키워드가 상품명에서
    # 더 뒤에 있을 때만 그쪽을 본체로 본다. 각 묶음 안의 우선순위(_RULES 순서)는 그대로 둔다.
    _MIDDLE_FORM_TYPES: ClassVar[frozenset[ProductTypeNormalized]] = frozenset(
        {
            ProductTypeNormalized.AMPOULE,
            ProductTypeNormalized.SERUM,
            ProductTypeNormalized.ESSENCE,
        }
    )
    _FINAL_FORM_TYPES: ClassVar[frozenset[ProductTypeNormalized]] = frozenset(
        {
            ProductTypeNormalized.TONER,
            ProductTypeNormalized.EMULSION,
            ProductTypeNormalized.LOTION,
            ProductTypeNormalized.CREAM,
        }
    )

    # 상품명으로 분류하지 못했을 때만 쓰는 원본 category3. 제품 형태와 1:1로 대응하는 값만 둔다.
    # `Moisturizers`처럼 크림·오일·토너가 섞인 넓은 카테고리는 유형을 추정할 수 없어 넣지 않는다.
    _TYPE_BY_SOURCE_CATEGORY: ClassVar[dict[str, ProductTypeNormalized]] = {
        "cleansers": ProductTypeNormalized.CLEANSER,
        "sunscreen": ProductTypeNormalized.SUNSCREEN,
        "sheet masks": ProductTypeNormalized.SHEET_MASK,
    }

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

    def classify(self, row: ProductCandidateRow) -> ProductTaxonomyResult:
        raw_text = f"{row.raw_title} {row.display_title}"
        title = self._normalize(raw_text)
        middle_form: tuple[ProductTaxonomyRule, str] | None = None
        final_form: tuple[ProductTaxonomyRule, str] | None = None
        for rule in self._RULES:
            matched_keyword = self._matches_rule(title, rule)
            if matched_keyword is None:
                continue
            # 구체적인 규칙은 먼저 나온 것이 그대로 이긴다. 형태 키워드는 뒤에서 함께 비교한다.
            if rule.product_type in self._MIDDLE_FORM_TYPES:
                middle_form = middle_form or (rule, matched_keyword)
            elif rule.product_type in self._FINAL_FORM_TYPES:
                final_form = final_form or (rule, matched_keyword)
            else:
                return self._result(
                    product_type=rule.product_type,
                    basis=TaxonomyDecisionBasis.TITLE,
                    matched_keyword=matched_keyword,
                )

        form = self._choose_form(raw_text, middle_form, final_form)
        if form is not None:
            rule, matched_keyword = form
            return self._result(
                product_type=rule.product_type,
                basis=TaxonomyDecisionBasis.TITLE,
                matched_keyword=matched_keyword,
            )

        source_category_type = self._TYPE_BY_SOURCE_CATEGORY.get(self._normalize(row.category3))
        if source_category_type is not None:
            return self._result(
                product_type=source_category_type,
                basis=TaxonomyDecisionBasis.SOURCE_CATEGORY,
                matched_keyword=row.category3,
            )

        return ProductTaxonomyResult(
            product_type_normalized=None,
            service_category=None,
            basis=TaxonomyDecisionBasis.UNCLASSIFIED,
        )

    def apply(self, row: ProductCandidateRow) -> ProductCandidateRow:
        result = self.classify(row)
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
    ) -> ProductTaxonomyResult:
        return ProductTaxonomyResult(
            product_type_normalized=product_type,
            service_category=self.service_category(product_type),
            basis=basis,
            matched_keyword=matched_keyword,
        )

    def _normalize(self, value: str) -> str:
        unescaped = html.unescape(value).casefold()
        return " ".join(re.sub(r"[^\w가-힣]+", " ", unescaped).split())

    def _contains(self, text: str, keyword: str) -> bool:
        normalized_keyword = self._normalize(keyword)
        return f" {normalized_keyword} " in f" {text} "

    def _choose_form(
        self,
        raw_text: str,
        middle_form: tuple[ProductTaxonomyRule, str] | None,
        final_form: tuple[ProductTaxonomyRule, str] | None,
    ) -> tuple[ProductTaxonomyRule, str] | None:
        if middle_form is None or final_form is None:
            return middle_form or final_form

        # "(+Toner 2.4ml+Cream 1.5g)"처럼 괄호 안의 증정·구성품은 제품 본체가 아니라서 위치 비교에서 뺀다.
        main_title = self._normalize(re.sub(r"\([^)]*\)", " ", raw_text))
        middle_position = self._last_keyword_position(main_title, middle_form[0])
        final_position = self._last_keyword_position(main_title, final_form[0])
        return final_form if final_position > middle_position else middle_form

    def _last_keyword_position(self, title: str, rule: ProductTaxonomyRule) -> int:
        padded_title = f" {title} "
        return max(padded_title.rfind(f" {self._normalize(keyword)} ") for keyword in rule.keywords)

    def _matches_rule(self, title: str, rule: ProductTaxonomyRule) -> str | None:
        if any(self._contains(title, keyword) for keyword in rule.excluded_keywords):
            return None
        return next(
            (keyword for keyword in rule.keywords if self._contains(title, keyword)),
            None,
        )
