"""성분 안전성·규제 근거(Evidence). CIR·MFDS 등 공식 출처만 담는다.

Knowledgedata(`IngredientKnowledgeFact`)와 달리 여기 담기는 내용은 전부 공식 기관
출처다. `topic`은 이 근거가 다루는 주제, `claim`은 핵심 결론, `conditions`는 그 결론이
성립하는 조건(사용 형태·농도·단서조항 등)이다.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
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


class EvidenceSourceType(StrEnum):
    """근거 출처. 공식 기관 출처만 추가한다."""

    MFDS_RESTRICTED_INGREDIENT = "mfds_restricted_ingredient"


class EvidenceTopic(StrEnum):
    """근거가 다루는 주제."""

    COSMETIC_USE_RESTRICTION = "cosmetic_use_restriction"


class EvidenceRegulateType(StrEnum):
    """MFDS 사용제한 원료정보의 `REGULATE_TYPE`."""

    PROHIBITED = "prohibited"
    LIMITED = "limited"


class Evidence(EntityBase):
    """CIR·MFDS 등 공식 출처의 성분 안전성·규제 근거 한 건."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('mfds_restricted_ingredient')",
            name="ck_evidence_source_type",
        ),
        CheckConstraint(
            "topic IN ('cosmetic_use_restriction')",
            name="ck_evidence_topic",
        ),
        CheckConstraint(
            "regulate_type IS NULL OR regulate_type IN ('prohibited', 'limited')",
            name="ck_evidence_regulate_type",
        ),
        table_options(comment="성분 안전성·규제 근거. CIR·MFDS 등 공식 출처만 담는다"),
    )

    ingredient_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingredient_master.id", ondelete="RESTRICT"),
        nullable=False,
        comment="근거가 적용되는 IngredientMaster 레코드",
    )
    topic: Mapped[EvidenceTopic] = mapped_column(
        _sql_enum(EvidenceTopic, length=40), nullable=False, comment="근거가 다루는 주제"
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False, comment="핵심 결론")
    conditions: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="결론이 성립하는 조건(사용 형태·농도·단서조항 등)"
    )
    jurisdiction: Mapped[str] = mapped_column(
        Text, nullable=False, comment="관할 국가/지역(예: 한국, EU, 중국)"
    )
    regulate_type: Mapped[EvidenceRegulateType | None] = mapped_column(
        _sql_enum(EvidenceRegulateType, length=20),
        nullable=True,
        comment="MFDS 규제유형(금지/한도). MFDS 출처가 아니면 NULL",
    )
    cas_no: Mapped[str | None] = mapped_column(Text, nullable=True, comment="CAS 등록번호")
    ingredient_synonym: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="이명(원본 콤마 구분 텍스트 그대로)"
    )
    notice_ingredient_name: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="고시원료명"
    )
    source_type: Mapped[EvidenceSourceType] = mapped_column(
        _sql_enum(EvidenceSourceType, length=40), nullable=False, comment="근거 출처 종류"
    )
    source_title: Mapped[str] = mapped_column(Text, nullable=False, comment="출처 문서/API 이름")
    source_url: Mapped[str] = mapped_column(Text, nullable=False, comment="출처 URL")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="원 출처의 발행/개정 시각(있는 경우만)"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="이 레코드를 수집한 시각",
    )
