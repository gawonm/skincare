"""add product taxonomy

Revision ID: 2d1f4b6a8c90
Revises: 7b85bd9f1045
Create Date: 2026-09-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 이 사용하는 리비전 식별자.
revision: str = "2d1f4b6a8c90"
down_revision: str | Sequence[str] | None = "7b85bd9f1045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column(
            "product_type_normalized",
            sa.Enum(
                "serum",
                "essence",
                "ampoule",
                "cream",
                "lotion",
                "emulsion",
                "toner",
                "toner_pad",
                "cleanser",
                "cleansing_foam",
                "cleansing_gel",
                "cleansing_oil",
                "cleansing_balm",
                "cleansing_water",
                "sheet_mask",
                "wash_off_mask",
                "sleeping_mask",
                "mask",
                "patch",
                "sunscreen",
                "mist",
                "facial_oil",
                "balm",
                "spot_treatment",
                "booster",
                "peeling",
                "all_in_one",
                name="producttypenormalized",
                native_enum=False,
                length=40,
            ),
            nullable=True,
            comment="상품명과 원본 카테고리로 정규화한 제품 세부 유형. 미확정이면 NULL",
        ),
    )
    op.add_column(
        "product",
        sa.Column(
            "service_category",
            sa.Enum(
                "에센스·세럼",
                "앰플",
                "크림·로션",
                "토너·패드",
                "클렌저",
                "마스크·패치",
                "선케어",
                "기타",
                name="productservicecategory",
                native_enum=False,
                length=20,
            ),
            nullable=True,
            comment="서비스 화면에서 사용하는 제품 그룹. 미확정이면 NULL",
        ),
    )


def downgrade() -> None:
    op.drop_column("product", "service_category")
    op.drop_column("product", "product_type_normalized")
