"""성분 표준화 사전(IngredientMaster).

KCIA 성분코드를 내부 ingredient_id로 그대로 쓰지 않고 별도 PK(EntityBase.id)를 두되,
`ingredient_code`에 유니크 제약을 걸어 KCIA 성분코드로 조회할 수 있게 한다. Knowledgedata,
MFDS, CIR, 제품 전성분에 서로 다른 이름으로 등장하는 동일 성분을 이 테이블의 한 행으로
통합한다.
"""

from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


class IngredientMaster(EntityBase):
    """KCIA 표준화명칭목록 기반 성분 마스터."""

    __tablename__ = "ingredient_master"
    __table_args__ = (
        UniqueConstraint("ingredient_code", name="uq_ingredient_master_ingredient_code"),
        table_options(
            comment="KCIA 표준화명칭목록 기반 성분 마스터. 성분 Entity Resolution용 사전"
        ),
    )

    ingredient_code: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="KCIA 성분표준화명칭목록의 성분코드(원본 식별자)"
    )
    standard_name_ko: Mapped[str] = mapped_column(Text, nullable=False, comment="표준 성분명(국문)")
    standard_name_en: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="표준 성분명(영문). PDF상 공란인 행이 있어 nullable"
    )
    old_names_ko: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default="{}",
        comment="구 국문 명칭 목록. PDF의 '|' 구분 값을 분리해 저장",
    )
    old_names_en: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default="{}",
        comment="구 영문 명칭 목록. PDF의 '|' 구분 값을 분리해 저장",
    )
    normalized_name_ko: Mapped[str] = mapped_column(
        Text, nullable=False, comment="표준 국문명에서 공백만 제거한 매칭용 키"
    )
    normalized_name_en: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="표준 영문명을 대소문자·공백·하이픈·괄호 기준으로 정규화한 매칭용 키",
    )
    source_version: Mapped[str] = mapped_column(
        Text, nullable=False, comment="KCIA 표준화명칭목록 발행 버전(예: '2026.08.31 기준')"
    )
