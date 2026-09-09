"""add unique natural key index on rag_chunk

Revision ID: 0ff194fd5f2f
Revises: 03ea827fb355
Create Date: 2026-09-10 00:02:43.053523

"""

from collections.abc import Sequence

from alembic import op

# Alembic 이 사용하는 리비전 식별자.
revision: str = '0ff194fd5f2f'
down_revision: str | Sequence[str] | None = '03ea827fb355'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # rag_chunk의 자연키는 "어느 소스 문서의 어느 필드·순번에서 나온 청크인가"다.
    # evidence_id/ingredient_knowledge_fact_id/nia_record_id 중 정확히 하나만 채워지므로
    # (ck_rag_chunk_exactly_one_source_ref), COALESCE로 하나의 표현식으로 묶는다. 재적재
    # 시 이 인덱스가 있어야 같은 문서·필드·순번을 upsert 대상으로 식별할 수 있다.
    # 적용 전 기존 데이터에 중복이 없음을 실제로 확인했다(2026-09-10).
    op.execute(
        "CREATE UNIQUE INDEX ux_rag_chunk_natural_key ON rag_chunk ("
        "source_table, "
        "COALESCE(evidence_id::text, ingredient_knowledge_fact_id::text, nia_record_id), "
        "chunk_field, chunk_index"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_rag_chunk_natural_key")
