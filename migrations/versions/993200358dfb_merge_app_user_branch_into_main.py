"""merge app_user branch into main

Revision ID: 993200358dfb
Revises: 459db45c7a64, b1f97294c64e
Create Date: 2026-09-10 16:20:43.384725

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 이 사용하는 리비전 식별자.
revision: str = '993200358dfb'
down_revision: str | Sequence[str] | None = ('459db45c7a64', 'b1f97294c64e')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
