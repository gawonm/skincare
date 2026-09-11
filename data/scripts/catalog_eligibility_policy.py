"""카테고리 목록에 노출된 상품 중 "정상 판매 중인 단일 구성" 상품만 골라낸다.

품절·판매종료·Gift Set·세트/리필/미니 상품은 수집하지 않되, 왜 제외했는지는
`CatalogEligibilityResult.reasons`에 남긴다 — 조용히 버리지 않고 실행 로그로 확인할 수
있게 한다. 옵션 개수는 목록 API에 정확한 값이 없어(`optn_yn`은 Y/N만 줌) 상세 조회 이후
`exceeds_option_limit()`로 별도 확인한다.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from data.scripts.oliveyoung_global_category_schemas import OliveYoungGlobalCategoryHitFields

# "30ml+30ml"처럼 용량 표기 사이에 낀 "+"만 묶음 판매 신호로 본다. 맨 "+" 문자만 보면
# "Dr.Jart+"처럼 브랜드명에 "+"가 들어간 상품까지 잘못 걸린다(실제 라이브 응답으로 확인함).
_VOLUME_BUNDLE_PATTERN = re.compile(r"\d\s*(?:ml|g)\s*\+\s*\d", re.IGNORECASE)


class CatalogExclusionReason(StrEnum):
    SOLD_OUT = "sold_out"
    NOT_FOR_SALE = "not_for_sale"
    GIFT_SET_CATEGORY = "gift_set_category"
    BUNDLE_KEYWORD = "bundle_keyword"
    REFILL_KEYWORD = "refill_keyword"
    MINI_KEYWORD = "mini_keyword"
    OPTION_COUNT_MULTIPLE = "option_count_multiple"


class CatalogEligibilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_eligible: bool
    reasons: tuple[CatalogExclusionReason, ...] = ()


class CatalogEligibilityPolicy:
    # Gift Set 하위 카테고리는 정의상 세트 구성이라 제목 키워드와 별개로 통째로 제외한다.
    _GIFT_SET_CATEGORY_NO = "1000000012"
    _SELL_STAT_CODE_ON_SALE = "10"
    _NOT_SOLD_OUT = "N"
    _SEARCHABLE = "Y"
    _SINGLE_OPTION_COUNT = 1

    # 이 키워드들은 실제 카탈로그로 검증한 목록이 아니라 최선의 추측이다. 소규모
    # 드라이런 결과 리포트를 보고 너무 세거나 느슨하면 조정한다.
    # "(+"는 라이브 응답으로 실제 확인한 패턴이다 — "Double Pack (+Birch Drop Serum 20ml)"처럼
    # 본품에 다른 상품을 얹어 파는 구성을 표시할 때 쓰인다.
    _BUNDLE_KEYWORDS = ("set", "bundle", "kit", "duo", "trio", "double pack", "(+")
    _REFILL_KEYWORDS = ("refill",)
    _MINI_KEYWORDS = ("mini", "travel size", "trial size", "sample")

    def evaluate(self, hit: OliveYoungGlobalCategoryHitFields) -> CatalogEligibilityResult:
        reasons: list[CatalogExclusionReason] = []

        if hit.sold_out_yn != self._NOT_SOLD_OUT:
            reasons.append(CatalogExclusionReason.SOLD_OUT)
        if (
            hit.sell_stat_code != self._SELL_STAT_CODE_ON_SALE
            or hit.srch_psblt_yn != self._SEARCHABLE
        ):
            reasons.append(CatalogExclusionReason.NOT_FOR_SALE)
        if self._GIFT_SET_CATEGORY_NO in hit.all_path_ctgr_no_list:
            reasons.append(CatalogExclusionReason.GIFT_SET_CATEGORY)

        name_lower = hit.prdt_name.lower()
        if any(
            keyword in name_lower for keyword in self._BUNDLE_KEYWORDS
        ) or _VOLUME_BUNDLE_PATTERN.search(hit.prdt_name):
            reasons.append(CatalogExclusionReason.BUNDLE_KEYWORD)
        if any(keyword in name_lower for keyword in self._REFILL_KEYWORDS):
            reasons.append(CatalogExclusionReason.REFILL_KEYWORD)
        if any(keyword in name_lower for keyword in self._MINI_KEYWORDS):
            reasons.append(CatalogExclusionReason.MINI_KEYWORD)

        return CatalogEligibilityResult(is_eligible=not reasons, reasons=tuple(reasons))

    def exceeds_option_limit(self, option_count: int) -> bool:
        """상세 조회 후 실제 옵션 개수로 2차 판정한다. 목록 API의 `optn_yn`은 Y/N만 줘서
        정확한 개수를 모르기 때문에 여기서 따로 확인한다."""
        return option_count > self._SINGLE_OPTION_COUNT
