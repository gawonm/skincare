"""MFDS/CIR/PubMed 근거 문서 단위 메타데이터.

`Claim(NIA)`과 분리된 Evidence 전용 저장소다(`docs/data/EVIDENCE_RAG_DESIGN.md` B절,
`docs/data/EVIDENCE_COVERAGE_AUDIT.md` 7절 Option B). 성분 연결은 이 테이블에 두지 않는다 -
하나의 evidence_chunk가 병용·충돌·비교 근거처럼 여러 성분을 동시에 다룰 수 있어서
`models.evidence_chunk.evidence_chunk_ingredient` 조인 테이블에서만 관리하고, 문서의 성분
목록은 그에 속한 청크들의 성분 관계에서 파생한다(별도 document-ingredient 조인 테이블 없음).
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, Text, UniqueConstraint, func
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


class EvidenceDocumentSourceType(StrEnum):
    """근거 문서의 출처 종류. `evidence_chunk.source_type`도 이 값을 그대로 비정규화해서 쓴다."""

    MFDS = "mfds"
    CIR = "cir"
    PUBMED_ABSTRACT = "pubmed_abstract"
    REGULATORY_OTHER = "regulatory_other"


class EvidenceLevel(StrEnum):
    """문서 자체의 출처 신뢰도 등급(`rag_chunk.confidence_tier`와 같은 성격).

    Claim-Evidence 매칭 강도(DIRECT/PARTIAL/WEAK 등)와는 다른 개념이다 - 그건 문서 속성이
    아니라 "이 claim과 이 evidence가 얼마나 관련 있는가"라는 관계 속성이라 `ClaimEvidenceLink`가
    소유하며(비영속 런타임 객체), 이 컬럼에는 없다.
    """

    OFFICIAL_REGULATORY = "official_regulatory"
    EXPERT_REVIEWED = "expert_reviewed"
    PEER_REVIEWED_STUDY = "peer_reviewed_study"


class EvidenceDocumentStatus(StrEnum):
    """CIR 전용. draft/tentative 문서를 production 근거로 잘못 쓰는 걸 막는다."""

    FINAL = "final"
    AMENDED_FINAL = "amended_final"
    TENTATIVE = "tentative"
    DRAFT = "draft"
    REREVIEW = "rereview"
    UNKNOWN = "unknown"


class EvidenceStudyType(StrEnum):
    """PubMed 전용. 연구 설계를 구분해 in vitro 근거를 human 근거로 오인하지 않게 한다."""

    HUMAN_STUDY = "human_study"
    IN_VITRO = "in_vitro"
    MIXED_IN_VITRO_AND_HUMAN = "mixed_in_vitro_and_human"
    ANIMAL_STUDY = "animal_study"
    REVIEW = "review"
    UNKNOWN = "unknown"


class EvidenceFormulationType(StrEnum):
    """PubMed 전용. 복합 제형 연구를 단일 성분 효과로 일반화하지 않기 위해 구분한다."""

    SINGLE_INGREDIENT = "single_ingredient"
    COMBINATION_FORMULATION = "combination_formulation"


class EvidenceClaimTopic(StrEnum):
    """이 문서가 다루는 claim 주제. 한 문서가 여러 값을 가질 수 있어 배열 컬럼에 담는다."""

    EFFICACY = "efficacy"
    PRECAUTION = "precaution"
    CONCENTRATION_REGULATION = "concentration_regulation"
    USAGE_INSTRUCTION = "usage_instruction"
    COMBINATION = "combination"


class EvidenceDocument(EntityBase):
    """MFDS/CIR/PubMed 근거 문서 한 건."""

    __tablename__ = "evidence_document"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", name="uq_evidence_document_source_type_source_id"
        ),
        CheckConstraint(
            "source_type IN ('mfds', 'cir', 'pubmed_abstract', 'regulatory_other')",
            name="ck_evidence_document_source_type",
        ),
        CheckConstraint(
            "evidence_level IN ('official_regulatory', 'expert_reviewed', 'peer_reviewed_study')",
            name="ck_evidence_document_evidence_level",
        ),
        CheckConstraint(
            "document_status IS NULL OR document_status IN "
            "('final', 'amended_final', 'tentative', 'draft', 'rereview', 'unknown')",
            name="ck_evidence_document_document_status",
        ),
        CheckConstraint(
            "study_type IS NULL OR study_type IN "
            "('human_study', 'in_vitro', 'mixed_in_vitro_and_human', 'animal_study', 'review', 'unknown')",
            name="ck_evidence_document_study_type",
        ),
        CheckConstraint(
            "formulation_type IS NULL OR formulation_type IN "
            "('single_ingredient', 'combination_formulation')",
            name="ck_evidence_document_formulation_type",
        ),
        table_options(
            comment="MFDS/CIR/PubMed 근거 문서 단위 메타데이터. Claim(NIA)과 분리된 Evidence 전용"
        ),
    )

    source_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="안정적 자연키(PMID:16766489, CIR 성분코드, MFDS 게시글ID 등). source_type과 묶어야 유일",
    )
    source_type: Mapped[EvidenceDocumentSourceType] = mapped_column(
        _sql_enum(EvidenceDocumentSourceType, length=20), nullable=False, comment="근거 출처 종류"
    )
    source_title: Mapped[str] = mapped_column(Text, nullable=False, comment="문서 제목")
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True, comment="발행 기관/저널")
    document_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="원 출처 발행/개정일"
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="출처 URL")
    doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    pmid: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="MFDS만 값 있음, CIR/PubMed는 보통 NULL"
    )
    language: Mapped[str] = mapped_column(Text, nullable=False, default="ko", server_default="ko")
    evidence_level: Mapped[EvidenceLevel] = mapped_column(
        _sql_enum(EvidenceLevel, length=30), nullable=False, comment="문서 자체의 출처 신뢰도 등급"
    )
    raw_ingredient_names: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        comment="원본 표기 그대로. 성분 FK 연결은 evidence_chunk_ingredient가 담당",
    )
    document_status: Mapped[EvidenceDocumentStatus | None] = mapped_column(
        _sql_enum(EvidenceDocumentStatus, length=20),
        nullable=True,
        comment="CIR 전용. MFDS/PubMed는 NULL",
    )
    study_type: Mapped[EvidenceStudyType | None] = mapped_column(
        _sql_enum(EvidenceStudyType, length=30),
        nullable=True,
        comment="PubMed 전용. MFDS/CIR는 NULL",
    )
    formulation_type: Mapped[EvidenceFormulationType | None] = mapped_column(
        _sql_enum(EvidenceFormulationType, length=30),
        nullable=True,
        comment="PubMed 전용. 복합 제형(niacinamide+glycerin 등) 구분",
    )
    claim_topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        comment="이 문서가 다루는 claim 주제(EvidenceClaimTopic 값들)",
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="MFDS/CIR/PubMed 원문·metadata를 가져온 시각. created_at(레코드 생성 시각)과는 별개",
    )
