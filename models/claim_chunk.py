"""NIA Claim 검색·임베딩 단위(statement 1개 = 청크 1개), 그리고 성분 연결 조인 테이블.

`docs/data/CLAIM_STORAGE_ERD.md` 3~4절 설계를 그대로 옮긴다.

`statement_id`는 annotation run(pilot/validation/production)마다 같은 값이 재사용된다
(같은 레코드를 다시 라벨링하면 "S001", "S002", ...가 그대로 다시 붙는다 - 실측 확인,
`CLAUDE_SESSION_BOARD.md` 2026-09-17 기록). 그래서 단독 UNIQUE를 걸지 않고
`UNIQUE(claim_document_id, statement_id)`로 - 같은 annotation run(=같은 claim_document) 안에서만
유일하면 된다.

`claim_chunk_ingredient`는 `evidence_chunk_ingredient`와 달리 `ingredient_id`가 NULL일 수
있다 - FROZEN `IngredientRef`가 raw_name만 있는 unresolved 상태를 허용하기 때문에(원문
표기는 보존하되 아직 표준 성분과 매칭되지 않은 상태도 정상 저장 대상). 그래서 복합 PK 대신
서러게이트 `id` PK + CHECK 제약을 쓴다.
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, EntityBase, table_options

# BAAI/bge-m3(local), 1024차원 - `models.evidence_chunk.EVIDENCE_EMBEDDING_DIMENSION`과 같은
# 이유로 별도 상수다(Claim/Evidence는 저장 테이블·검색 경로가 분리돼 있고, `rag_chunk`의
# 1536차원과도 무관 - `docs/data/CLAIM_STORAGE_ERD.md` 5절, 2026-09-17 결정).
CLAIM_EMBEDDING_DIMENSION = 1024


def _sql_enum(enum_cls: type, *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class ClaimStatementType(StrEnum):
    """`data.scripts.nia_labeling_schemas.NiaStatementType`과 값만 맞춰 별도 선언(import 방향 규칙)."""

    CASE_OBSERVATION = "case_observation"
    CAUSE_CLAIM = "cause_claim"
    INGREDIENT_EFFECT_CLAIM = "ingredient_effect_claim"
    PRECAUTION = "precaution"
    USAGE_INSTRUCTION = "usage_instruction"
    COMBINATION_CLAIM = "combination_claim"
    CONTEXTUAL_FACTOR = "contextual_factor"


class ClaimIngestionDecision(StrEnum):
    """`data.scripts.nia_claim_ingestion_policy.NiaClaimIngestionDecision`과 값만 맞춰 별도 선언.

    운영 검색 인덱스 필터 컬럼(`decision`)의 값 집합 - `ingestible_structured`/
    `ingestible_free_text`만 기본 검색 대상이고 나머지는 제외한다(Shared Decisions #6,
    `docs/coordination/CLAUDE_SESSION_BOARD.md`)."""

    BLOCKED = "blocked"
    HUMAN_REVIEW = "human_review"
    INGESTIBLE_STRUCTURED = "ingestible_structured"
    INGESTIBLE_FREE_TEXT = "ingestible_free_text"


class ClaimPriority(StrEnum):
    """`data.scripts.nia_claim_ingestion_policy.NiaClaimPriority`와 값만 맞춰 별도 선언."""

    PRIMARY = "primary"
    SECONDARY = "secondary"


class ClaimSupportStatus(StrEnum):
    """`data.scripts.nia_labeling_schemas.NiaSupportStatus`와 값만 맞춰 별도 선언.
    현재 파이프라인은 항상 `unverified`만 생성하지만, 스키마 자체는 4종을 정의한다."""

    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class ClaimIngredientMatchingStatus(StrEnum):
    """`data.scripts.nia_labeling_schemas.NiaIngredientMatchingStatus`와 값만 맞춰 별도 선언."""

    UNRESOLVED = "unresolved"
    UNRESOLVED_AMBIGUOUS_FAMILY = "unresolved_ambiguous_family"
    MATCHED = "matched"
    REJECTED = "rejected"


class ClaimIngredientRefRole(StrEnum):
    """FROZEN `data.scripts.nia_claim_document.IngredientRefRole`과 값만 맞춰 별도 선언.
    2026-09-16 PHASE 1 동결 기준 현재는 전부 `unspecified`만 생성되지만, 컬럼 자체는
    3종을 정의해 미래 확장을 막지 않는다."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    UNSPECIFIED = "unspecified"


class ClaimChunk(EntityBase):
    """NIA Claim statement 한 건 - 검색·임베딩 대상."""

    __tablename__ = "claim_chunk"
    __table_args__ = (
        UniqueConstraint(
            "claim_document_id", "statement_id", name="uq_claim_chunk_document_statement"
        ),
        CheckConstraint(
            "statement_type IN ('case_observation', 'cause_claim', 'ingredient_effect_claim', "
            "'precaution', 'usage_instruction', 'combination_claim', 'contextual_factor')",
            name="ck_claim_chunk_statement_type",
        ),
        CheckConstraint(
            "decision IN ('blocked', 'human_review', 'ingestible_structured', 'ingestible_free_text')",
            name="ck_claim_chunk_decision",
        ),
        CheckConstraint("priority IN ('primary', 'secondary')", name="ck_claim_chunk_priority"),
        CheckConstraint(
            "support_status IN ('unverified', 'supported', 'contradicted', 'insufficient')",
            name="ck_claim_chunk_support_status",
        ),
        Index(
            "ix_claim_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_claim_chunk_document_id", "claim_document_id"),
        Index("ix_claim_chunk_decision", "decision"),
        table_options(
            comment="NIA Claim statement 단위 검색·임베딩 청크. Evidence와 분리된 Claim 전용"
        ),
    )

    claim_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("claim_document.id", ondelete="CASCADE"),
        nullable=False,
        comment="이 statement가 속한 NIA 레코드/annotation run",
    )
    statement_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="ClaimDocument(Pydantic).statement_id. annotation run마다 재사용되므로 claim_document_id와 묶어야 유일",
    )
    statement_type: Mapped[ClaimStatementType] = mapped_column(
        _sql_enum(ClaimStatementType, length=30), nullable=False
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="임베딩 대상 원문. ClaimDocument.content(mapper가 이미 통일한 텍스트)",
    )
    source_spans: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        comment="ClaimDocument.source_spans(json_path/quote/start/end) 그대로. 원문 재검증용",
    )
    decision: Mapped[ClaimIngestionDecision] = mapped_column(
        _sql_enum(ClaimIngestionDecision, length=25),
        nullable=False,
        comment="운영 검색 인덱스 필터. ingestible_* 만 기본 검색 대상(Shared Decisions #6)",
    )
    priority: Mapped[ClaimPriority] = mapped_column(
        _sql_enum(ClaimPriority, length=15), nullable=False
    )
    support_status: Mapped[ClaimSupportStatus] = mapped_column(
        _sql_enum(ClaimSupportStatus, length=15),
        nullable=False,
        comment="현재 파이프라인은 항상 unverified",
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(CLAIM_EMBEDDING_DIMENSION),
        nullable=False,
        comment="content의 임베딩 벡터. BAAI/bge-m3(local), 1024차원",
    )
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, comment="벡터를 만든 모델명")


# `evidence_chunk_ingredient`와 달리 ingredient_id가 NULL일 수 있어(unresolved raw_name-only
# 케이스, FROZEN IngredientRef가 허용) 복합 PK 대신 서러게이트 id + CHECK 제약을 쓴다.
# matched ingredient 중복 방지용 unique constraint는 실제 데이터 중복 패턴을 먼저 확인한 뒤
# 적용하기로 결정됨(2026-09-17) - 지금은 넣지 않는다.
claim_chunk_ingredient = Table(
    "claim_chunk_ingredient",
    Base.metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "claim_chunk_id",
        Uuid,
        ForeignKey("claim_chunk.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ingredient_id",
        Uuid,
        ForeignKey("ingredient_master.id", ondelete="CASCADE"),
        nullable=True,
        comment="matching_status='matched'일 때만 non-null",
    ),
    Column(
        "raw_name",
        Text,
        nullable=True,
        comment="IngredientRef.raw_name - unresolved든 matched든 원문 있으면 보존",
    ),
    Column(
        "matching_status",
        _sql_enum(ClaimIngredientMatchingStatus, length=30),
        nullable=False,
    ),
    Column("role", _sql_enum(ClaimIngredientRefRole, length=15), nullable=False),
    CheckConstraint(
        "ingredient_id IS NOT NULL OR raw_name IS NOT NULL",
        name="ck_claim_chunk_ingredient_has_identity",
    ),
    CheckConstraint(
        "matching_status IN ('unresolved', 'unresolved_ambiguous_family', 'matched', 'rejected')",
        name="ck_claim_chunk_ingredient_matching_status",
    ),
    CheckConstraint(
        "role IN ('primary', 'secondary', 'unspecified')", name="ck_claim_chunk_ingredient_role"
    ),
    Index("ix_claim_chunk_ingredient_ingredient_id", "ingredient_id", "claim_chunk_id"),
    Index("ix_claim_chunk_ingredient_claim_chunk_id", "claim_chunk_id"),
    comment="claim_chunk ↔ ingredient_master 연결. unresolved(raw_name만 있는) 언급도 보존",
    info={"managed": True},
)
