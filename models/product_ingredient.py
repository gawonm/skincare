"""상품 전성분(INCI) 원문 스냅샷과, 그 안의 성분 토큰별 표준 성분 매칭 결과.

원문 수집·구간 분리·토큰화는 올리브영 세션(`data/scripts/product_ingredient_text_parser.py`,
`data/scripts/product_ingredient_option_linker.py`)이 담당하고, 그 결과(`ProductIngredientParseResult`)를
받아 `IngredientMaster`로 매칭·저장하는 건 이 RAG 세션 담당이다
(`docs/oliveyoung_global_pipeline_handoff.md` 참고).

두 테이블로 나눈 이유:
- `ProductIngredientSnapshot`: 원문 자체(재현·재검토 기준). 상품 하나에 한 행.
- `ProductIngredient`: 그 원문을 토큰 단위로 나눈 결과 + 매칭 결과. 상품 하나에 여러 행.
매칭 실패(미매칭) 토큰도 버리지 않고 이 테이블에 `ingredient_id=NULL`로 남긴다 - "이
상품에 어떤 성분이 있는지 몰랐다"와 "이 토큰이 무엇인지 아직 못 밝혔다"를 구분해야
나중에 재매칭(마스터 갱신 후)이나 사람 검토가 가능하다.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


def _sql_enum(enum_cls: type[StrEnum], *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class ProductIngredientSectionLinkStatus(StrEnum):
    """`data.scripts.product_ingredient_parse_schemas.IngredientSectionLinkStatus`와 값을 맞춘다.

    이 값을 별도로 여기 다시 선언하는 이유: `models/`는 `data/scripts/`를 import하지 않는다
    (`scripts`는 일회성 ETL이라 `models → core`만 지키는 계층 규칙 밖에 있다, STRUCTURE.md
    참고). 두 Enum의 값(`.value`)이 어긋나면 저장 시점에 바로 드러나므로 안전하다.
    """

    NO_OPTION_SECTIONS = "no_option_sections"
    LINKED = "linked"
    AMBIGUOUS = "ambiguous"


class ProductIngredientTokenParseStatus(StrEnum):
    """`data.scripts.product_ingredient_parse_schemas.IngredientTokenParseStatus`와 값을 맞춘다."""

    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"


class IngredientMatchAcceptance(StrEnum):
    """이 토큰의 표준 성분 매칭 결과를 그대로 확정(RAG 근거 연결에 쓸 수 있음)해도 되는지.

    `IngredientNameMatcher`는 건드리지 않는다(다른 파이프라인의 매칭 동작을 바꾸면 안 됨).
    대신 호출부(`ProductIngredientMatchAcceptancePolicy`)에서 결과의 `method`를 보고
    이 상태만 따로 매긴다 - 영문 정규화 일치(`STANDARD_NAME_EN_NORMALIZED`/
    `OLD_NAME_EN_NORMALIZED`)만 자동 확정하고, annotation-stripped나 fuzzy(원래 한글 전용)
    결과는 전성분표에는 국문명이 없는 경우가 대부분이라 실제로 걸릴 일이 없지만 방어적으로
    전부 사람 검토로 돌린다.
    """

    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"
    UNMATCHED = "unmatched"


class ProductIngredientSnapshot(EntityBase):
    """상품 하나의 전성분 원문 한 벌. 재파싱해도 내용이 같으면 새 행을 만들지 않는다."""

    __tablename__ = "product_ingredient_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_product_id",
            "raw_text_hash",
            name="uq_product_ingredient_snapshot_source_product_hash",
        ),
        table_options(
            comment="상품 전성분(INCI) 원문 스냅샷. source+source_product_id+원문 해시로 중복 방지"
        ),
    )

    source: Mapped[str] = mapped_column(
        Text, nullable=False, comment="예: 'oliveyoung_global'. candidate_id는 여기 쓰지 않는다"
    )
    source_product_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="쇼핑몰 상품 ID(candidate_id 아님 - 재수집마다 안 바뀌는 영구 식별자)",
    )
    raw_ingredients_text: Mapped[str] = mapped_column(
        Text, nullable=False, comment="원문 그대로. 재현·재검토 기준"
    )
    raw_text_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="raw_ingredients_text의 해시(sha256). 재수집 시 내용 불변 여부를 빠르게 확인",
    )
    parser_version: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment=(
            "이 스냅샷을 토큰화한 파서 버전. 파서가 바뀌면(예: 새 구분자 처리 추가) "
            "이 값으로 재파싱 대상을 가려낸다"
        ),
    )


class ProductIngredient(EntityBase):
    """전성분 원문 안 성분 토큰 하나 + 표준 성분 매칭 결과.

    매칭 실패해도 행을 만든다(버리지 않는다) - `ingredient_id IS NULL`이 "미매칭"이다.
    """

    __tablename__ = "product_ingredient"
    __table_args__ = (
        CheckConstraint(
            "section_link_status IN ('no_option_sections', 'linked', 'ambiguous')",
            name="ck_product_ingredient_section_link_status",
        ),
        CheckConstraint(
            "token_parse_status IN ('parsed', 'needs_review')",
            name="ck_product_ingredient_token_parse_status",
        ),
        CheckConstraint(
            "match_acceptance IN ('confirmed', 'needs_review', 'unmatched')",
            name="ck_product_ingredient_match_acceptance",
        ),
        # 같은 스냅샷을 재파싱해도 이 토큰이 어느 자리였는지 안정적으로 다시 찾을 수
        # 있어야 upsert(무변경 스킵)가 가능하다 - 구간 순서 + 구간 안 토큰 순서로 식별.
        UniqueConstraint(
            "snapshot_id",
            "section_sequence",
            "token_order",
            name="uq_product_ingredient_snapshot_position",
        ),
        Index("ix_product_ingredient_ingredient_id", "ingredient_id"),
        table_options(comment="전성분 원문의 성분 토큰 하나 + IngredientMaster 매칭 결과"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_ingredient_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    section_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="원문 안 구간(옵션 라벨) 순서. 0부터"
    )
    section_label: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="원문 그대로의 [라벨] 텍스트. 구간이 없으면 NULL"
    )
    section_link_status: Mapped[ProductIngredientSectionLinkStatus] = mapped_column(
        _sql_enum(ProductIngredientSectionLinkStatus, length=20),
        nullable=False,
        comment="이 구간이 실제 판매 옵션과 연결됐는지(LINKED만 특정 옵션의 성분으로 쓸 수 있음)",
    )
    linked_option_gds_cd: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="section_link_status=LINKED일 때만 채워지는 판매 옵션 식별자(gds_cd)",
    )
    token_order: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="구간 안에서 성분이 나열된 순서. 0부터"
    )
    raw_token: Mapped[str] = mapped_column(
        Text, nullable=False, comment="원문 그대로(구분자 분리 + 트리밍만). 매칭 실패해도 보존"
    )
    matching_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="매칭에 실제로 쓴 이름(함량 괄호 제거, 상용명 괄호는 보존)"
    )
    concentration_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="괄호 안 함량 표기 원문(있으면)"
    )
    token_parse_status: Mapped[ProductIngredientTokenParseStatus] = mapped_column(
        _sql_enum(ProductIngredientTokenParseStatus, length=20),
        nullable=False,
        comment="NEEDS_REVIEW면 raw_token이 두 성분명이 붙은 것일 수 있어 매칭을 시도하지 않는다",
    )
    token_review_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="token_parse_status=NEEDS_REVIEW일 때만 채워짐"
    )
    ingredient_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingredient_master.id", ondelete="SET NULL"),
        nullable=True,
        comment="매칭된 표준 성분. 미매칭이면 NULL(행은 유지)",
    )
    match_method: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="IngredientNameMatcher가 반환한 IngredientMatchMethod 값. 시도 전이면 NULL",
    )
    match_acceptance: Mapped[IngredientMatchAcceptance] = mapped_column(
        _sql_enum(IngredientMatchAcceptance, length=20),
        nullable=False,
        comment=(
            "CONFIRMED만 RAG 근거 연결에 쓴다. matcher 결과가 있어도 method가 영문 정규화 "
            "일치가 아니면 NEEDS_REVIEW로 내린다(matcher 자체는 수정하지 않는다)"
        ),
    )
    match_review_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="match_acceptance != CONFIRMED일 때 왜 자동 확정하지 않았는지",
    )
