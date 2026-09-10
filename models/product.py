"""상품 카탈로그(이름·가격·이미지). 전성분 매칭 결과는 여기 담지 않는다.

`scripts/product_candidate_schemas.py`의 `ProductCandidateRow`가 이 테이블의 CSV 형태다.
소스(올리브영 글로벌 등) + 수집 방식(성분 키워드 검색/카테고리 전수 크롤링)에 상관없이
같은 테이블에 담고, 크롤링마다 `(source, source_product_id)` 기준으로 최신 상태 한 행만
유지한다(UPSERT) — 가격·재고 이력은 이번 범위에 없다. 이력이 필요해지면 별도 테이블로
분리한다(이 테이블을 append-only로 바꾸지 않는다. 그러면 "현재가"를 구할 때마다 매번
최신 행을 찾는 쿼리가 필요해진다).

전성분 원문(`raw_ingredients_text`)은 여기 중복 저장하지 않는다.
`product_ingredient_snapshot`이 이미 `(source, source_product_id)`로 원문을 보관하므로,
필요하면 그 테이블을 조인한다 — 두 곳에 같은 원문을 두면 재크롤링 시 한쪽만 갱신되는
사고가 날 수 있다.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


def _sql_enum(enum_cls: type[StrEnum], *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class ProductTargetGroup(StrEnum):
    """`scripts.product_candidate_schemas.TargetGroup`과 값을 맞춘다.

    `models`는 `scripts`를 import하지 않으므로(STRUCTURE.md 의존 방향) 값을 여기 다시
    선언한다. 카테고리 전수 크롤링으로 모은 행은 특정 성분에 배정하지 않아 NULL이다.
    """

    VITAMIN_C = "아스코빅애씨드"
    NIACINAMIDE = "나이아신아마이드"
    RETINOL = "레티놀"
    AHA = "글라이콜릭애씨드"
    BHA = "살리실릭애씨드"


class ProductTitleSource(StrEnum):
    """`scripts.product_candidate_schemas.TitleSource`와 값을 맞춘다."""

    NATIVE_KR = "native_kr"
    OLIVEYOUNG_KR = "oliveyoung_kr"
    TRANSLATED = "translated"
    UNTRANSLATED = "untranslated"


class ProductPriceBand(StrEnum):
    """`scripts.product_candidate_schemas.PriceBand`와 값을 맞춘다."""

    UNDER_10K = "1만원 미만"
    BAND_10K = "1만원대"
    BAND_20K = "2만원대"
    BAND_30K_40K = "3~4만원대"
    OVER_50K = "5만원 이상"


class ProductMatchStatus(StrEnum):
    """`scripts.product_candidate_schemas.MatchStatus`와 값을 맞춘다."""

    MATCHED = "matched"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    REJECTED = "rejected"


class Product(EntityBase):
    """상품 카탈로그 한 건의 최신 상태. 소스+상품ID당 한 행만 유지한다."""

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("source", "source_product_id", name="uq_product_source_product_id"),
        table_options(comment="상품 카탈로그(이름·가격·이미지)의 최신 상태. 이력 저장소 아님"),
    )

    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="예: 'oliveyoung_global'. product_ingredient_snapshot.source와 값을 맞춘다",
    )
    source_product_id: Mapped[str] = mapped_column(
        Text, nullable=False, comment="쇼핑몰 상품 ID. candidate_id(수집 실행 순번)는 저장하지 않는다"
    )
    search_query: Mapped[str] = mapped_column(
        Text, nullable=False, comment="이 행을 찾은 검색어. 카테고리 전수 크롤링이면 'category:<코드>'"
    )
    target_group: Mapped[ProductTargetGroup | None] = mapped_column(
        _sql_enum(ProductTargetGroup, length=20),
        nullable=True,
        comment="성분 키워드 검색으로 모은 행만 채움. 카테고리 크롤링 행은 NULL",
    )
    raw_title: Mapped[str] = mapped_column(
        Text, nullable=False, comment="수집한 원본 상품명. 고치지 않는다 — 재매칭의 기준"
    )
    display_title: Mapped[str] = mapped_column(Text, nullable=False, comment="화면 노출용 한글 상품명")
    title_source: Mapped[ProductTitleSource] = mapped_column(
        _sql_enum(ProductTitleSource, length=20),
        nullable=False,
        comment="display_title의 신뢰도 구분. TRANSLATED/UNTRANSLATED는 공식명 아님",
    )
    brand: Mapped[str] = mapped_column(Text, nullable=False, comment="브랜드명")
    maker: Mapped[str | None] = mapped_column(Text, nullable=True, comment="제조사. 소스가 안 주면 NULL")
    category1: Mapped[str] = mapped_column(Text, nullable=False, comment="대분류")
    category2: Mapped[str | None] = mapped_column(Text, nullable=True, comment="중분류")
    category3: Mapped[str | None] = mapped_column(Text, nullable=True, comment="소분류")
    lowest_price: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="올리브영 글로벌: 할인가(실제 지불가). 네이버 쇼핑: 판매처 간 최저가",
    )
    highest_price: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="올리브영 글로벌: 정가. 네이버 쇼핑: 판매처 간 최고가"
    )
    price_band: Mapped[ProductPriceBand] = mapped_column(
        _sql_enum(ProductPriceBand, length=20), nullable=False, comment="lowest_price 기준 가격대"
    )
    volume_value: Mapped[float | None] = mapped_column(
        Numeric, nullable=True, comment="제목에서 추출한 단일 용량. 복수/세트/미확정이면 NULL(0 아님)"
    )
    volume_unit: Mapped[str | None] = mapped_column(Text, nullable=True, comment="예: 'ml', 'g'")
    image_url: Mapped[str] = mapped_column(Text, nullable=False, comment="원본 이미지 URL")
    local_image_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="저장소 루트 기준 상대경로. DB만 넘기면 이미지 파일은 안 따라간다"
    )
    shopping_url: Mapped[str] = mapped_column(Text, nullable=False, comment="상품 상세 페이지 URL")
    mall_name: Mapped[str] = mapped_column(Text, nullable=False, comment="판매처명")
    product_type: Mapped[str] = mapped_column(
        Text, nullable=False, comment="현재 관측값 'GENERAL_PRODUCT' 하나뿐이라 아직 Enum으로 좁히지 않음"
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="이 상태를 수집한 시각(크롤러 관측 시각)"
    )
    match_status: Mapped[ProductMatchStatus] = mapped_column(
        _sql_enum(ProductMatchStatus, length=30),
        nullable=False,
        comment="수집 직후는 항상 MANUAL_REVIEW_REQUIRED. 전성분 검증 전 자동 MATCHED 없음",
    )
    review_reasons: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default="{}",
        comment="검토가 필요한 구체적 사유들(ReviewReason 값). 비어 있어도 검토 완료 아님",
    )
