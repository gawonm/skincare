"""merge taxonomy and user profile heads

Revision ID: d4c2a7e91b30
Revises: 2d1f4b6a8c90, b518f9fd7cf7
Create Date: 2026-09-11 00:00:00.000000

"""

from collections.abc import Sequence

revision: str = "d4c2a7e91b30"
down_revision: str | Sequence[str] | None = ("2d1f4b6a8c90", "b518f9fd7cf7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 두 독립 스키마 변경은 각 부모 리비전에서 이미 끝나므로 실행할 SQL이 없다.
    pass


def downgrade() -> None:
    # merge 지점만 되돌리고 두 부모 스키마는 그대로 둔다.
    pass
