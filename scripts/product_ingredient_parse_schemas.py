"""전성분(INCI) 원문을 성분 단위로 나눈 파싱 결과가 주고받는 Enum·Pydantic 모델.

이 모듈은 텍스트 파싱·옵션 연결까지만 다룬다. 표준 성분(`IngredientMaster`) 매칭, DB
저장, RAG 근거 연결은 다른 세션(RAG 파이프라인) 담당이라 여기서 다루지 않는다
(docs/oliveyoung_global_pipeline_handoff.md 참고).

원문은 어떤 단계에서도 임의로 변형하지 않는다 — 콤마를 무조건 구분자로 보거나 괄호를
일괄 제거하면 `1,2-Hexanediol`, `Ammonium Acryloyldimethyltaurate/VP Copolymer`,
`Citrus Aurantium Dulcis (Orange) Peel Oil` 같은 실제 성분명이 깨진다.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from scripts.product_candidate_schemas import DataSource


class IngredientTokenParseStatus(StrEnum):
    """성분 토큰 하나를 얼마나 신뢰할 수 있게 분리했는지."""

    # 구분자(콤마)가 명확해 안전하게 분리됐다.
    PARSED = "parsed"
    # 구분자 누락 등이 의심돼(예: 두 성분명이 콤마 없이 이어붙은 것으로 보임) 사람이
    # 원문을 직접 확인해야 한다. 이 상태에서는 임의로 나누지 않고 원문을 통째로 남긴다.
    NEEDS_REVIEW = "needs_review"


class ParsedIngredientToken(BaseModel):
    """전성분 목록에서 콤마로 나눈 성분 하나."""

    model_config = ConfigDict(frozen=True)

    # 이 구간(섹션) 안에서 원문에 등장한 순서. 0부터 시작. 전성분은 배합량이 많은
    # 순서대로 표기하는 관례가 있어(국내 화장품법 5% 초과 성분 한정) 순서 자체가 정보다.
    order: int
    # 콤마 분리 + 앞뒤 공백 제거만 한 원문. 그 외 어떤 변형도 하지 않는다.
    raw_token: str
    # 매칭용 이름. `raw_token`에서 끝에 붙은 함량·각주 괄호(예: "(2,000 ppm)")만 제거한
    # 값이다. 식물 일반명 괄호(예: "(Orange)")나 이명 대괄호(예: "[Vitamin C]")는
    # 성분 식별에 필요한 정보라 제거하지 않고 그대로 남긴다.
    matching_name: str
    # 원문 끝에 붙어 있던 함량·각주 괄호 원문(있으면). 없으면 None.
    concentration_text: str | None
    parse_status: IngredientTokenParseStatus
    # NEEDS_REVIEW 일 때만 채운다. 왜 review가 필요한지 사람이 읽을 수 있는 문장.
    review_reason: str | None = None


class IngredientSectionLinkStatus(StrEnum):
    """이 구간(옵션 라벨)이 실제 판매 옵션과 어떻게 연결되는지.

    `candidate_id`나 번역된 상품명은 재수집마다 바뀔 수 있어 연결키로 쓰지 않는다
    (`docs/oliveyoung_global_pipeline_handoff.md` 4절 "candidate_id는 실행마다 안
    바뀐다는 보장이 없다" 참고). 연결은 항상 소스 옵션 식별자(`gds_cd`) 기준이다.
    """

    # 원문에 `[옵션명]` 구간 자체가 없다 — 상품 수준의 단일 INCI 원문만 확인됐다는
    # 뜻이다. 옵션이 여러 개인 상품이라도 옵션별 배합이 실제로 같은지는 이 사실
    # 하나만으로 확정할 수 없다 — 별도로 검증하기 전까지는 "상품 수준 단일 원문
    # 제공됨"이라는 사실만 기록한다.
    NO_OPTION_SECTIONS = "no_option_sections"
    # 구간 라벨이 판매 옵션 목록 중 정확히 하나와만 대응돼 연결이 확정됐다.
    LINKED = "linked"
    # 구간 라벨이 여러 옵션과 겹치거나 어떤 옵션과도 안 겹쳐 연결을 확정할 수 없다.
    AMBIGUOUS = "ambiguous"


class IngredientSectionParse(BaseModel):
    """전성분 원문 안의 한 구간(옵션 없는 상품은 구간이 통째로 하나)."""

    model_config = ConfigDict(frozen=True)

    # "[옵션명]" 원문 라벨. 옵션 구간이 없는 상품이면 None.
    section_label: str | None
    # 이 구간의 성분 목록 원문(라벨 줄 제외). 손대지 않고 그대로 보존한다.
    section_raw_text: str
    link_status: IngredientSectionLinkStatus
    # LINKED 일 때만 채운다. 연결된 판매 옵션의 `gds_cd`(OliveYoungGlobalProductOption).
    linked_option_gds_cd: str | None = None
    tokens: tuple[ParsedIngredientToken, ...]


class ProductIngredientParseResult(BaseModel):
    """상품 하나의 전성분 원문 파싱 결과 전체.

    상품 식별자는 `(source, source_product_id)` 조합이다. `source_product_id` 만으로는
    소스가 다르면 값이 우연히 겹칠 수 있고, `ProductCandidateRow.candidate_id`는
    재수집마다 바뀔 수 있어 식별자로 쓰지 않는다
    (`docs/oliveyoung_global_pipeline_handoff.md` 4절 참고). 옵션(판매 단위) 식별자는
    `IngredientSectionParse.linked_option_gds_cd`(올리브영 글로벌
    `OliveYoungGlobalProductOption.gds_cd`) — `source_product_id` 하나가 여러 `gds_cd`를
    가질 수 있다.
    """

    model_config = ConfigDict(frozen=True)

    source: DataSource
    source_product_id: str
    # 원문 전체. 어떤 처리도 거치지 않은 그대로. 재현·재검토의 기준.
    raw_ingredients_text: str
    sections: tuple[IngredientSectionParse, ...]
