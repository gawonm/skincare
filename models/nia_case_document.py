"""NIA 사례 검색용 문서와 BGE-M3 벡터 저장 모델."""

from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options

NIA_CASE_EMBEDDING_DIMENSION = 1024


class NiaCaseDatasetSplit(StrEnum):
    TRAINING = "training"
    VALIDATION = "validation"


def _sql_enum(enum_cls: type[StrEnum], *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class NiaCaseDocument(EntityBase):
    """AI Hub Q-CoT-A 사례 한 건을 검색 단위 한 건으로 저장한다."""

    __tablename__ = "nia_case_document"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "text_version",
            "embedding_model",
            name="uq_nia_case_document_case_text_model",
        ),
        CheckConstraint(
            "dataset_split IN ('training', 'validation')",
            name="ck_nia_case_document_dataset_split",
        ),
        CheckConstraint(
            "age BETWEEN 10 AND 39",
            name="ck_nia_case_document_age_range",
        ),
        CheckConstraint(
            "source_line_number >= 1",
            name="ck_nia_case_document_source_line_number",
        ),
        Index(
            "ix_nia_case_document_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_nia_case_document_retrieval_scope",
            "dataset_split",
            "text_version",
            "embedding_model",
        ),
        Index("ix_nia_case_document_case_id", "case_id"),
        table_options(
            comment="NIA 사례 검색 문서. 사례 1건당 BGE-M3 1024차원 벡터 1개를 저장"
        ),
    )

    case_id: Mapped[str] = mapped_column(Text, nullable=False, comment="NIA 원본 사례 식별자")
    dataset_split: Mapped[NiaCaseDatasetSplit] = mapped_column(
        _sql_enum(NiaCaseDatasetSplit, length=20),
        nullable=False,
        comment="원본 데이터셋의 training/validation 구분",
    )
    source_archive_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="입력 ZIP 파일명"
    )
    source_member_name: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="ZIP 내부 JSONL 파일명"
    )
    source_line_number: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="원본 JSONL 행 번호"
    )
    page_content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="질문·답변·전체 CoT를 조립한 표시용 본문"
    )
    embedding_text: Mapped[str] = mapped_column(
        Text, nullable=False, comment="임베딩 입력 본문. nia_case_text/v1에서는 page_content와 동일"
    )
    text_version: Mapped[str] = mapped_column(
        Text, nullable=False, comment="NIA 사례 본문 조립 규칙 버전"
    )
    target_concern: Mapped[str] = mapped_column(
        Text, nullable=False, comment="주요 피부 고민 필터 값"
    )
    gender: Mapped[str] = mapped_column(Text, nullable=False, comment="성별 필터 값")
    age: Mapped[int] = mapped_column(Integer, nullable=False, comment="10~39세 연령 필터 값")
    skin_type: Mapped[str] = mapped_column(Text, nullable=False, comment="피부 유형 필터 값")
    skin_concerns: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
        comment="복수 피부 고민 필터 값",
    )
    case_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        comment="NiaCaseDocument.metadata 원형 JSON",
    )
    content_hash: Mapped[str] = mapped_column(
        Text, nullable=False, comment="embedding_text의 SHA-256"
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(NIA_CASE_EMBEDDING_DIMENSION),
        nullable=False,
        comment="BAAI/bge-m3 정규화 벡터",
    )
    embedding_model: Mapped[str] = mapped_column(
        Text, nullable=False, comment="벡터 생성 모델명"
    )
