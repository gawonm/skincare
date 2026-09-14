"""제품 전성분 토큰 ↔ ingredient master 매칭 결과가 주고받는 Pydantic 모델."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from data.scripts.product_candidate_schemas import DataSource, TargetGroup


class ProductQualityStatus(StrEnum):
    VALID = "valid"
    EXCLUDED = "excluded"
    REVIEW_REQUIRED = "review_required"


class ProductIngredientMappingRow(BaseModel):
    """전성분 토큰 하나 ↔ ingredient master 매칭 결과 한 행."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    source: DataSource
    source_product_id: str
    target_group: TargetGroup | None
    raw_token: str
    matching_name: str
    ingredient_id: UUID | None
    matching_status: str
    match_method: str


class ProductQualityRow(BaseModel):
    """제품 후보 한 행의 최종 품질 판정."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    source: DataSource
    source_product_id: str
    target_group: TargetGroup | None
    status: ProductQualityStatus
    reasons: tuple[str, ...]
