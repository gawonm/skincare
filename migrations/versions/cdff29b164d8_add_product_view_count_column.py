"""add product view_count column

Revision ID: cdff29b164d8
Revises: 9f4c2a7d8e61
Create Date: 2026-09-23 13:51:55.179001

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 이 사용하는 리비전 식별자.
revision: str = "cdff29b164d8"
down_revision: str | Sequence[str] | None = "9f4c2a7d8e61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column(
            "view_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="상품 상세 조회수 카운터. GET /products/{id} 호출마다 원자적으로 증가",
        ),
    )


def downgrade() -> None:
    op.drop_column("product", "view_count")
