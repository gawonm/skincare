"""Knowledgedata.xlsx에서 정제한 성분 지식(효능·권장 피부타입·주의사항 등).

Knowledgedata는 PubChem·COOS·CIR 등 출처가 혼합돼 있고 국내 규제 근거가 명확하지 않다.
그래서 `compounding_regulation_text`(배합규제 원문)는 MFDS 사용제한 원료정보와
교차검증되기 전까지 `regulatory_confidence=UNVERIFIED`로 저장하고, 국내 배합 규제에
관한 확정적 답변의 근거로 쓰지 않는다.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


class RegulatoryConfidence(StrEnum):
    """`compounding_regulation_text`의 신뢰 수준."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class IngredientKnowledgeFact(EntityBase):
    """Knowledgedata.xlsx 한 행을 정제해 `IngredientMaster`와 연결한 성분 지식."""

    __tablename__ = "ingredient_knowledge_fact"
    __table_args__ = (
        UniqueConstraint("source_row_no", name="uq_ingredient_knowledge_fact_source_row_no"),
        CheckConstraint(
            "regulatory_confidence IN ('verified', 'unverified')",
            name="ck_ingredient_knowledge_fact_regulatory_confidence",
        ),
        table_options(comment="Knowledgedata.xlsx 정제 결과. RAG Document 생성의 입력"),
    )

    ingredient_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingredient_master.id", ondelete="RESTRICT"),
        nullable=False,
        comment="매칭된 IngredientMaster 레코드. 매칭 실패 행은 여기 적재하지 않고 수동 검토 큐로 보낸다",
    )
    source_row_no: Mapped[int] = mapped_column(
        nullable=False,
        comment=(
            "Knowledgedata.xlsx의 실제 엑셀 행 번호. 원본 'No' 컬럼은 2,465개 중 451개가 "
            "비어 있어 식별자로 쓰지 않는다"
        ),
    )
    inci_name: Mapped[str] = mapped_column(Text, nullable=False, comment="원본 '성분명(INCI)' 컬럼")
    name_ko: Mapped[str | None] = mapped_column(Text, nullable=True, comment="원본 '한글명' 컬럼")
    efficacy: Mapped[str | None] = mapped_column(Text, nullable=True, comment="효능")
    recommended_skin_types: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="권장피부타입(원본 자유 텍스트)"
    )
    precautions: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="사용상주의사항(안전성)"
    )
    recommended_concentration: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="권장농도(원본 자유 텍스트, 예: '0.5~7.0%')"
    )
    compounding_regulation_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="배합규제 원문. 국가가 혼재돼 있어 MFDS 교차검증 전에는 국내 기준으로 쓰지 않는다",
    )
    raw_material_source: Mapped[str | None] = mapped_column(Text, nullable=True, comment="원료출처")
    source_reference: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="원시 데이터 출처(참고문헌 file명)"
    )
    regulatory_confidence: Mapped[RegulatoryConfidence] = mapped_column(
        SqlEnum(
            RegulatoryConfidence,
            native_enum=False,
            length=20,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=RegulatoryConfidence.UNVERIFIED,
        comment="compounding_regulation_text가 MFDS와 교차검증됐는지 여부",
    )
