"""merge chat history and NIA case heads

Revision ID: 9f4c2a7d8e61
Revises: 2063ce3feae3, a7d3c91e5f42
Create Date: 2026-09-20 23:24:00

"""

from collections.abc import Sequence

revision: str = "9f4c2a7d8e61"
down_revision: str | Sequence[str] | None = (
    "2063ce3feae3",
    "a7d3c91e5f42",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 두 부모 migration이 실제 테이블을 만들기 때문에 merge 지점에서는 추가 SQL이 필요 없다.
    return None


def downgrade() -> None:
    # merge 이력만 분리하며 각 부모의 schema 변경은 부모 migration이 되돌린다.
    return None
