"""RAG 검색·답변 생성에 쓰는 임베딩 청크.

`Evidence`, `IngredientKnowledgeFact`, NIA AI Hub Q&A(dataset 71886, DB 테이블 아님 -
`nia_record_id`로만 참조) 세 소스를 하나의 임베딩 인덱스에 담는다. 소스마다 별도
테이블을 두지 않는 이유는 "성분 X에 대한 모든 근거"를 한 번의 벡터 검색으로 찾아야
하기 때문이다 - 소스별 테이블이면 검색 시점에 N개 쿼리를 합쳐야 한다.

청킹 단위는 "의미단위 하나 = 청크 하나"다(길이 기반 스플리터 아님). `chunk_field`가
그 의미단위가 원본의 어느 필드였는지 기록한다.
"""

from enum import StrEnum
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options

# text-embedding-3-small의 출력 차원. 임베딩 모델을 바꾸면 기존 벡터를 전부 다시
# 만들어야 하므로(agent/rag/embedding/__init__.py 참고) 이 상수도 같이 바꿔야 한다.
EMBEDDING_DIMENSION = 1536


def _sql_enum(enum_cls: type[StrEnum], *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class RagSourceTable(StrEnum):
    """청크의 원본이 어느 소스인지."""

    EVIDENCE = "evidence"
    INGREDIENT_KNOWLEDGE_FACT = "ingredient_knowledge_fact"
    NIA_QA = "nia_qa"


class RagChunkField(StrEnum):
    """청크 하나가 원본의 어느 필드(의미단위)였는지."""

    EVIDENCE_CLAIM = "evidence_claim"
    EVIDENCE_CONDITIONS = "evidence_conditions"
    KNOWLEDGE_EFFICACY = "knowledge_efficacy"
    KNOWLEDGE_RECOMMENDED_SKIN_TYPES = "knowledge_recommended_skin_types"
    KNOWLEDGE_PRECAUTIONS = "knowledge_precautions"
    KNOWLEDGE_RECOMMENDED_CONCENTRATION = "knowledge_recommended_concentration"
    NIA_QUESTION = "nia_question"
    NIA_ANSWER = "nia_answer"
    NIA_COT_STEP = "nia_cot_step"


class RagConfidenceTier(StrEnum):
    """RAG가 사용자에게 출처를 보여줄 때 구분하는 신뢰도 등급.

    OFFICIAL_REGULATORY: MFDS 등 공식 규제기관 원문(Evidence).
    STRUCTURED_KNOWLEDGE: 사람이 미리 구조화한 성분 지식(IngredientKnowledgeFact).
    AI_GENERATED_REVIEWED: AI가 생성하고 전문가 패널이 검증한 데이터(NIA Q&A/CoT).
    """

    OFFICIAL_REGULATORY = "official_regulatory"
    STRUCTURED_KNOWLEDGE = "structured_knowledge"
    AI_GENERATED_REVIEWED = "ai_generated_reviewed"


class RagChunk(EntityBase):
    """임베딩된 근거 청크 하나."""

    __tablename__ = "rag_chunk"
    __table_args__ = (
        CheckConstraint(
            "source_table IN ('evidence', 'ingredient_knowledge_fact', 'nia_qa')",
            name="ck_rag_chunk_source_table",
        ),
        CheckConstraint(
            "chunk_field IN ("
            "'evidence_claim', 'evidence_conditions', "
            "'knowledge_efficacy', 'knowledge_recommended_skin_types', "
            "'knowledge_precautions', 'knowledge_recommended_concentration', "
            "'nia_question', 'nia_answer', 'nia_cot_step'"
            ")",
            name="ck_rag_chunk_chunk_field",
        ),
        CheckConstraint(
            "confidence_tier IN "
            "('official_regulatory', 'structured_knowledge', 'ai_generated_reviewed')",
            name="ck_rag_chunk_confidence_tier",
        ),
        # 소스 테이블 하나당 그 소스를 가리키는 참조가 정확히 하나만 있어야 한다.
        # evidence/ingredient_knowledge_fact는 FK, nia_qa는 DB 테이블이 없어 문자열
        # 식별자(info.id)로만 참조한다.
        CheckConstraint(
            "(source_table = 'evidence' AND evidence_id IS NOT NULL "
            "  AND ingredient_knowledge_fact_id IS NULL AND nia_record_id IS NULL)"
            " OR (source_table = 'ingredient_knowledge_fact' AND evidence_id IS NULL "
            "  AND ingredient_knowledge_fact_id IS NOT NULL AND nia_record_id IS NULL)"
            " OR (source_table = 'nia_qa' AND evidence_id IS NULL "
            "  AND ingredient_knowledge_fact_id IS NULL AND nia_record_id IS NOT NULL)",
            name="ck_rag_chunk_exactly_one_source_ref",
        ),
        Index(
            "ix_rag_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_rag_chunk_ingredient_id", "ingredient_id"),
        table_options(
            comment="RAG 검색·답변 생성에 쓰는 임베딩 청크. Evidence/IngredientKnowledgeFact/NIA Q&A 통합 인덱스"
        ),
    )

    ingredient_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingredient_master.id", ondelete="CASCADE"),
        nullable=True,
        comment="관련 IngredientMaster. NIA Q&A는 한 성분에 매이지 않는 상황 설명이라 NULL 허용",
    )
    source_table: Mapped[RagSourceTable] = mapped_column(
        _sql_enum(RagSourceTable, length=30), nullable=False, comment="청크의 원본 소스"
    )
    evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), nullable=True
    )
    ingredient_knowledge_fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingredient_knowledge_fact.id", ondelete="CASCADE"), nullable=True
    )
    nia_record_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="NIA jsonl의 info.id. DB 테이블이 없는 소스라 FK 대신 문자열로 참조",
    )
    chunk_field: Mapped[RagChunkField] = mapped_column(
        _sql_enum(RagChunkField, length=40),
        nullable=False,
        comment="원본의 어느 필드(의미단위)에서 나온 청크인지",
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="같은 chunk_field 안에서의 순번. NIA_COT_STEP은 추론 단계 번호",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="임베딩 대상 원문")
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSION), nullable=False, comment="content의 임베딩 벡터"
    )
    embedding_model: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="벡터를 만든 임베딩 모델명. 모델이 바뀌면 이 값으로 재임베딩 대상을 가려낸다",
    )
    confidence_tier: Mapped[RagConfidenceTier] = mapped_column(
        _sql_enum(RagConfidenceTier, length=30),
        nullable=False,
        comment="사용자에게 출처를 보여줄 때 구분하는 신뢰도 등급",
    )
    cites_cir: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        comment=(
            "IngredientKnowledgeFact의 원시 데이터 출처/저작권해결방안에 CIR 인용이 "
            "포함돼 있는지. CIR 안전성 근거 1단계(별도 스크래핑 없이 기존 텍스트에서 식별)"
        ),
    )
    source_title: Mapped[str] = mapped_column(
        Text, nullable=False, comment="출처 표시용 제목. 조회 시 원본 테이블 조인을 피하려 비정규화"
    )
    source_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="공식 출처 URL(Evidence). NIA Q&A는 NULL"
    )
    citation_refs: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        comment="PMID/DOI 등 인용 식별자 목록(NIA Q&A의 evidence_sources)",
    )
