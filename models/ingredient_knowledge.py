"""Knowledgedata.xlsx에서 정제한 성분 지식(효능·권장 피부타입·주의사항 등).

Knowledgedata는 PubChem·COOS·CIR 등 출처가 혼합돼 있고 국내 규제 근거가 명확하지 않다.
그래서 `compounding_regulation_text`(배합규제 원문)는 MFDS 사용제한 원료정보와
교차검증되기 전까지 `regulatory_confidence=UNVERIFIED`로 저장하고, 국내 배합 규제에
관한 확정적 답변의 근거로 쓰지 않는다.

이 파일은 NIA AI Hub "스킨케어 성분-효능 추천 데이터"(dataset 71886)의 원천데이터③
`지식성분데이터.xlsx`와 동일 파일로 확인됐다(2026-09-09). `copyright_resolution`(저작권
해결방안)은 그 데이터셋이 행마다 남긴 출처별 라이선스 근거이며, RAG가 근거를 사용자에게
보여줄 때 "공공데이터"와 "제한적 이용허락 데이터"를 구분하는 신뢰도 신호로 쓴다.
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
    chemical_properties: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="화학적물성"
    )
    product_characteristics: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="제품적특성"
    )
    solubility: Mapped[str | None] = mapped_column(Text, nullable=True, comment="용해도")
    molecular_formula: Mapped[str | None] = mapped_column(Text, nullable=True, comment="분자식")
    molecular_weight: Mapped[str | None] = mapped_column(Text, nullable=True, comment="분자량")
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
    copyright_resolution: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="저작권해결방안. 행별 출처 라이선스 근거(예: 공공데이터/이용허락계약)",
    )
    token_count: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="토큰. 원본이 단일 숫자가 아닌 경우가 있어 문자열로 그대로 보존",
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
