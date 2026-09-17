"""Evidence RAG 검색·임베딩 단위, 그리고 성분 연결 조인 테이블.

`evidence_document`가 문서 단위 정보를 갖고, 이 청크는 그중 검색 필터에 쓰는 필드
(`source_type`/`source_title`/`url`/`doi`/`pmid`/`jurisdiction`/`evidence_level`)만
비정규화해서 들고 있다(`rag_chunk`의 관례를 그대로 따름).

`chunk_id`(자연키, 재수집 시 같은 청크를 다시 찾는 용도)와 citation locator
(`document_id`/`page`/`section`/`chunk_index`/`content_hash`/`parser_version`)를 분리한다 -
Backend citation은 `chunk_id` 문자열을 파싱하지 않고 이 독립 컬럼들을 그대로 조합해서 만든다.

`evidence_chunk_ingredient`는 성분 연결 전용 순수 조인 테이블이다. 하나의 청크가 병용·충돌·
비교 근거처럼 여러 성분을 동시에 다룰 수 있어 단일 FK 대신 다대다로 뒀다(Session A
`EvidenceQueryAnchor` 다중 성분 요구사항 반영). 추가 속성이 없어 `EntityBase`를 상속하는
ORM 엔티티 클래스 대신 `Table`로 선언한다.
"""

from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, EntityBase, table_options
from models.evidence_document import EvidenceDocumentSourceType, EvidenceLevel

# `rag_chunk.EMBEDDING_DIMENSION`(1536, text-embedding-3-small)과 별개 상수다 - Evidence는
# rag_chunk와 저장 테이블·검색 경로가 이미 분리돼 있고(evidence_document/evidence_chunk),
# 임베딩도 BAAI/bge-m3(local, 1024차원)로 별도 확정됐다(2026-09-17). rag_chunk의 1536차원
# 결정(docs/erd/app.md "임베딩 차원 유지 결정 — 2026-09-11")은 이 변경과 무관하게 유지된다.
EVIDENCE_EMBEDDING_DIMENSION = 1024


def _sql_enum(enum_cls: type, *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class EvidenceChunk(EntityBase):
    """Evidence RAG 검색·임베딩 대상 청크 하나."""

    __tablename__ = "evidence_chunk"
    __table_args__ = (
        UniqueConstraint("chunk_id", name="uq_evidence_chunk_chunk_id"),
        CheckConstraint(
            "source_type IN ('mfds', 'cir', 'pubmed_abstract', 'regulatory_other')",
            name="ck_evidence_chunk_source_type",
        ),
        CheckConstraint(
            "evidence_level IN ('official_regulatory', 'expert_reviewed', 'peer_reviewed_study')",
            name="ck_evidence_chunk_evidence_level",
        ),
        Index(
            "ix_evidence_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_evidence_chunk_document_id", "document_id"),
        table_options(
            comment="Evidence RAG(MFDS/CIR/PubMed) 검색·임베딩 청크. Claim(NIA)과 분리된 저장소"
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_document.id", ondelete="CASCADE"),
        nullable=False,
        comment="citation locator 구성요소로 직접 쓰임(chunk_id 문자열 파싱 아님)",
    )
    chunk_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment='결정적 자연키 "{source_id}:{page}:{section}:{chunk_index}". 재수집 매칭 전용',
    )
    source_type: Mapped[EvidenceDocumentSourceType] = mapped_column(
        _sql_enum(EvidenceDocumentSourceType, length=20),
        nullable=False,
        comment="document에서 비정규화",
    )
    source_title: Mapped[str] = mapped_column(Text, nullable=False, comment="document에서 비정규화")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="CIR PDF만 값 있음")
    section: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="PubMed는 'abstract' 고정, MFDS는 NULL"
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="같은 document 안에서의 순번"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="임베딩 대상 원문. 요약하지 않고 원문 그대로"
    )
    content_hash: Mapped[str] = mapped_column(
        Text, nullable=False, comment="content의 sha256. 재수집 시 원문 불변 여부 확인용"
    )
    parser_version: Mapped[str] = mapped_column(
        Text, nullable=False, comment="이 청크를 만든 파서/청킹 로직 버전"
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EVIDENCE_EMBEDDING_DIMENSION),
        nullable=False,
        comment="content의 임베딩 벡터. BAAI/bge-m3(local), 1024차원 - rag_chunk(1536)와 별도",
    )
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, comment="벡터를 만든 모델명")
    url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="document에서 비정규화")
    doi: Mapped[str | None] = mapped_column(Text, nullable=True, comment="document에서 비정규화")
    pmid: Mapped[str | None] = mapped_column(Text, nullable=True, comment="document에서 비정규화")
    jurisdiction: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="document에서 비정규화"
    )
    evidence_level: Mapped[EvidenceLevel] = mapped_column(
        _sql_enum(EvidenceLevel, length=30), nullable=False, comment="document에서 비정규화"
    )


# 순수 다대다 조인 테이블 - 자체 속성이 없어 ORM 엔티티 클래스 대신 Table로 선언한다.
# Base.metadata에 등록되므로 config.yaml의 model_modules에 이 모듈(models.evidence_chunk)만
# 추가하면 Alembic autogenerate에도 그대로 잡힌다(EvidenceChunk 클래스와 같은 모듈).
evidence_chunk_ingredient = Table(
    "evidence_chunk_ingredient",
    Base.metadata,
    Column(
        "evidence_chunk_id",
        Uuid,
        ForeignKey("evidence_chunk.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ingredient_id",
        Uuid,
        ForeignKey("ingredient_master.id", ondelete="CASCADE"),
        nullable=False,
    ),
    PrimaryKeyConstraint("evidence_chunk_id", "ingredient_id", name="pk_evidence_chunk_ingredient"),
    Index(
        "ix_evidence_chunk_ingredient_ingredient_id",
        "ingredient_id",
        "evidence_chunk_id",
    ),
    comment=(
        "evidence_chunk ↔ ingredient_master 다대다. 청크 하나가 병용/충돌/비교처럼 여러 성분을 "
        "동시에 다룰 수 있어 단일 FK 대신 조인 테이블로 뗀다"
    ),
    info={"managed": True},
)
