"""제품 후보 수집 단계가 주고받는 Enum 과 Pydantic 모델. 소스(네이버 쇼핑/올리브영 글로벌
등)에 상관없이 공통으로 쓴다.

단계 간에 dict 나 튜플을 그대로 넘기지 않는다.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DataSource(StrEnum):
    """`product_candidates.csv` 한 행이 어느 소스에서 왔는지."""

    NAVER_SHOPPING = "naver_shopping"
    OLIVEYOUNG_GLOBAL = "oliveyoung_global"


class TargetGroup(StrEnum):
    """MVP 성분군 화이트리스트 단위. `docs/data.md` 의 성분 범위 표와 일치시킨다.

    값은 `data/Knowledgedata.xlsx` 의 '한글명' 컬럼과 정확히 일치하는 KCIA/Knowledgedata
    표준 국문명이다 (영문 소비자용 이름이 아니다). AHA/BHA 는 산(acid) 종류 자체가
    아니라 이 프로젝트가 다루는 대표 성분(글라이콜릭애씨드/살리실릭애씨드) 으로 잡았다.
    """

    VITAMIN_C = "아스코빅애씨드"
    NIACINAMIDE = "나이아신아마이드"
    RETINOL = "레티놀"
    AHA = "글라이콜릭애씨드"
    BHA = "살리실릭애씨드"


class TitleSource(StrEnum):
    """`display_title` 이 어디서 왔는지. `ProductTitleTranslator` 참고.

    화면에는 `display_title` 만 노출하고, `title_source` 로 신뢰도를 구분한다 —
    번역 결과를 공식명인 척 보여주면 안 된다.
    """

    NATIVE_KR = "native_kr"  # 소스 자체가 한국어라 번역이 필요 없음 (예: 네이버 쇼핑)
    OLIVEYOUNG_KR = "oliveyoung_kr"  # 한국 올리브영 공식 상품명과 매칭됨 (현재는 접근 자체가 막혀 있어 아직 없음)
    TRANSLATED = "translated"  # 사람(또는 LLM)이 번역한 이름. 공식명 확인 전이라는 뜻.
    UNTRANSLATED = "untranslated"  # 매핑 테이블에 없어 raw_title(영문) 그대로 노출 중.


class PriceBand(StrEnum):
    """`lowest_price` 기준 가격대. 경계값은 `PriceBandClassifier` 에서 관리한다."""

    UNDER_10K = "1만원 미만"
    BAND_10K = "1만원대"
    BAND_20K = "2만원대"
    BAND_30K_40K = "3~4만원대"
    OVER_50K = "5만원 이상"


class ReviewReason(StrEnum):
    """`match_status=manual_review_required` 인 행이 정확히 왜 검토가 필요한지.

    행 하나에 여러 사유가 동시에 붙을 수 있다 (`ProductCandidateRow.review_reasons`).
    사유를 안 남기면 전부 "그냥 검토 필요"로 뭉뚱그려져서, 나중에 어떤 종류의 검토가
    끝났는지 추적할 수 없다.
    """

    # 상품이 옵션을 여러 개 가지고 있어(`optionList` 2개 이상), 대표 옵션 하나만 골라
    # 가격·용량을 채웠다. 다른 옵션은 성분·용량이 다를 수 있다.
    OPTION_AMBIGUOUS = "option_ambiguous"
    # 같은 source_product_id 가 다른 target_group 에도 등장한다. 상품명만으로는 어떤
    # 옵션이 어느 성분군에 해당하는지 구분할 수 없다. (공통/자동 태그 — 아래 두 값 중
    # 사람이 실제로 확인한 세부 케이스를 `data/manual_review/review_reason_overrides.csv`
    # 로 추가한다. 이 값 자체의 의미는 좁히지 않는다.)
    DUPLICATE_PRODUCT_ACROSS_GROUPS = "duplicate_product_across_groups"
    # 사람이 확인한 결과, source_product_id 가 같고 raw_title/가격도 동일 — 진짜 같은
    # SKU(옵션 구분 없음)가 여러 성분을 라벨에 같이 표기해서 여러 target_group 검색에
    # 걸린 경우. 예: "APLB Retinol Vitamin C Vitamin E Body Lotion" 이 레티놀 검색과
    # 아스코빅애씨드 검색에 둘 다 걸림.
    SAME_PRODUCT_MULTI_SEARCH_GROUP = "same_product_multi_search_group"
    # 사람이 확인한 결과, source_product_id 는 같지만 옵션 매칭기가 target_group 마다
    # 서로 다른 옵션을 정확히 찾아 raw_title/옵션이 실제로 다름 — 옵션 정보는 보존돼
    # 있으나, source_product_id 만으로 후속 중복 제거를 하면 이 옵션 구분이 사라질
    # 위험이 있다는 뜻. 예: 아누아 마스크팩의 "Niacinamide 5 TXA" vs "Retinol Niacin".
    DIFFERENT_OPTIONS_SAME_PRODUCT = "different_options_same_product"
    # raw_title(수집 원문)이 브랜드 공식 표기와 다를 수 있다는 의심이 확인된 경우
    # (예: OliveYoung Global 원문은 "Retinol"인데 브랜드 공식 페이지는 "Retinal").
    # `data/manual_review/review_reason_overrides.csv` 에서 수동으로 붙인다.
    RAW_TITLE_SOURCE_CONFLICT = "raw_title_source_conflict"
    # OPTION_AMBIGUOUS 로 걸렸지만 사람이 실제 옵션 목록을 확인해 보니 성분이 다른
    # 옵션이 섞인 게 아니라 수량/세트(1ea vs 9+1ea 등)만 다른 경우였음을 확인했다는 뜻.
    # 대표 옵션의 가격·성분은 신뢰할 수 있고, 다만 수량 기준이 무엇인지만 검토가 필요하다.
    # `data/manual_review/review_reason_overrides.csv` 에서 수동으로 붙인다.
    OPTION_QUANTITY_VARIANT_ONLY = "option_quantity_variant_only"


class MatchStatus(StrEnum):
    """제품 매칭 상태. 후보 수집 단계에서는 항상 `MANUAL_REVIEW_REQUIRED` 로 시작한다.

    검색 결과에는 전성분이 없어 자동으로 `MATCHED` 로 확정할 수 없기 때문이다.
    """

    MATCHED = "matched"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    REJECTED = "rejected"


class ProductCandidateRow(BaseModel):
    """`data/processed/product_candidates.csv` 한 행.

    아직 전성분을 검증하지 않은 후보다. `verified_products.csv` 로 옮기기 전까지
    추천에 사용하지 않는다 (`docs/data.md` 참고).

    `lowest_price`/`highest_price` 의미는 소스마다 다르다:
    - 네이버 쇼핑: 여러 판매처에 걸친 실제 최저가/최고가.
    - 올리브영 글로벌: 판매처가 하나뿐이라 할인가(`lowest_price`)/정가(`highest_price`)
      로 채운다. `PriceBandClassifier` 가 `lowest_price` 기준으로 분류하므로, 두 소스
      모두 "실제 지불가"를 기준으로 같은 가격대 분류를 받는다.
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    source: DataSource
    target_group: TargetGroup
    search_query: str
    source_product_id: str
    # 수집한 원본 상품명. 절대 고치지 않는다 — 출처 추적과 재매칭의 기준이 된다.
    raw_title: str
    # 화면에 노출할 한글 상품명. `title_source` 로 신뢰도를 같이 본다.
    display_title: str
    title_source: TitleSource
    brand: str
    maker: str
    category1: str
    category2: str
    category3: str
    lowest_price: int
    highest_price: int
    price_band: PriceBand
    # "1.5ml"처럼 소수 용량도 있어 int로 반올림하지 않는다 (`ProductVolumeParser` 참고).
    volume_value: float | None = None
    volume_unit: str | None = None
    image_url: str
    # 수집 시점에 내려받은 이미지의 로컬 경로 (`ImageDownloader` 참고). 프로젝트 루트
    # 기준 상대경로 문자열로 저장한다 (예: "data/processed/images/oliveyoung_global_GA240824996.jpg").
    local_image_path: str
    shopping_url: str
    mall_name: str
    product_type: str
    observed_at: datetime
    match_status: MatchStatus
    # 검토가 필요한 구체적 이유들. 비어 있으면 사유가 아직 안 붙은 것이지, 검토가
    # 필요 없다는 뜻이 아니다 (모든 행이 기본적으로 MANUAL_REVIEW_REQUIRED 다).
    review_reasons: tuple[ReviewReason, ...] = ()
