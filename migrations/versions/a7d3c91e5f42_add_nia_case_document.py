"""add nia_case_document table

Revision ID: a7d3c91e5f42
Revises: 3165318c750d
Create Date: 2026-09-20

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d3c91e5f42"
down_revision: str | Sequence[str] | None = "3165318c750d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nia_case_document",
        sa.Column("case_id", sa.Text(), nullable=False, comment="NIA 원본 사례 식별자"),
        sa.Column(
            "dataset_split",
            sa.Enum(
                "training",
                "validation",
                name="niacasedatasetsplit",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            comment="원본 데이터셋의 training/validation 구분",
        ),
        sa.Column("source_archive_name", sa.Text(), nullable=False, comment="입력 ZIP 파일명"),
        sa.Column("source_member_name", sa.Text(), nullable=True, comment="ZIP 내부 JSONL 파일명"),
        sa.Column("source_line_number", sa.Integer(), nullable=False, comment="원본 JSONL 행 번호"),
        sa.Column(
            "page_content",
            sa.Text(),
            nullable=False,
            comment="질문·답변·전체 CoT를 조립한 표시용 본문",
        ),
        sa.Column(
            "embedding_text",
            sa.Text(),
            nullable=False,
            comment="임베딩 입력 본문. nia_case_text/v1에서는 page_content와 동일",
        ),
        sa.Column("text_version", sa.Text(), nullable=False, comment="NIA 사례 본문 조립 규칙 버전"),
        sa.Column("target_concern", sa.Text(), nullable=False, comment="주요 피부 고민 필터 값"),
        sa.Column("gender", sa.Text(), nullable=False, comment="성별 필터 값"),
        sa.Column("age", sa.Integer(), nullable=False, comment="10~39세 연령 필터 값"),
        sa.Column("skin_type", sa.Text(), nullable=False, comment="피부 유형 필터 값"),
        sa.Column(
            "skin_concerns",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
            comment="복수 피부 고민 필터 값",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="NiaCaseDocument.metadata 원형 JSON",
        ),
        sa.Column("content_hash", sa.Text(), nullable=False, comment="embedding_text의 SHA-256"),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(dim=1024),
            nullable=False,
            comment="BAAI/bge-m3 정규화 벡터",
        ),
        sa.Column("embedding_model", sa.Text(), nullable=False, comment="벡터 생성 모델명"),
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="레코드 고유 식별자",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="레코드 생성 시각(UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="레코드 최종 수정 시각(UTC)",
        ),
        sa.CheckConstraint(
            "age BETWEEN 10 AND 39", name="ck_nia_case_document_age_range"
        ),
        sa.CheckConstraint(
            "dataset_split IN ('training', 'validation')",
            name="ck_nia_case_document_dataset_split",
        ),
        sa.CheckConstraint(
            "source_line_number >= 1",
            name="ck_nia_case_document_source_line_number",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id",
            "text_version",
            "embedding_model",
            name="uq_nia_case_document_case_text_model",
        ),
        comment="NIA 사례 검색 문서. 사례 1건당 BGE-M3 1024차원 벡터 1개를 저장",
        info={"managed": True},
    )
    op.create_index(
        "ix_nia_case_document_case_id",
        "nia_case_document",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        "ix_nia_case_document_embedding_hnsw",
        "nia_case_document",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_nia_case_document_retrieval_scope",
        "nia_case_document",
        ["dataset_split", "text_version", "embedding_model"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_nia_case_document_retrieval_scope", table_name="nia_case_document"
    )
    op.drop_index(
        "ix_nia_case_document_embedding_hnsw",
        table_name="nia_case_document",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_nia_case_document_case_id", table_name="nia_case_document")
    op.drop_table("nia_case_document")
