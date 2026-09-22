"""Claim chunk와 성분 연결을 저장하는 Repository."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.claim_chunk import (
    ClaimIngredientMatchingStatus,
    ClaimIngredientRefRole,
    claim_chunk_ingredient,
)


class ClaimChunkIngredientRepositoryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ClaimChunkIngredientUpsert(ClaimChunkIngredientRepositoryModel):
    claim_chunk_id: UUID
    ingredient_id: UUID | None = None
    raw_name: str | None = Field(default=None, min_length=1)
    matching_status: ClaimIngredientMatchingStatus
    role: ClaimIngredientRefRole

    @model_validator(mode="after")
    def validate_identity(self) -> "ClaimChunkIngredientUpsert":
        if self.ingredient_id is None and self.raw_name is None:
            raise ValueError("ingredient_id와 raw_name 중 하나는 있어야 합니다.")
        if (
            self.ingredient_id is not None
            and self.matching_status is not ClaimIngredientMatchingStatus.MATCHED
        ):
            raise ValueError("ingredient_id가 있으면 matching_status는 matched여야 합니다.")
        return self


class ClaimChunkIngredientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_chunks(
        self, chunk_ids: list[UUID], records: list[ClaimChunkIngredientUpsert]
    ) -> int:
        if not chunk_ids:
            return 0
        await self._session.execute(
            delete(claim_chunk_ingredient).where(
                claim_chunk_ingredient.c.claim_chunk_id.in_(chunk_ids)
            )
        )
        if records:
            await self._session.execute(
                insert(claim_chunk_ingredient).values(
                    [self._to_values(record) for record in records]
                )
            )
        return len(records)

    def _to_values(self, record: ClaimChunkIngredientUpsert) -> dict[str, Any]:
        return {
            "claim_chunk_id": record.claim_chunk_id,
            "ingredient_id": record.ingredient_id,
            "raw_name": record.raw_name,
            "matching_status": record.matching_status.value,
            "role": record.role.value,
        }
