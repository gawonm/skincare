"""Agent 성분 식별 포트용 `ingredient_master` 읽기 Repository."""

from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class IngredientLookupRow(BaseModel):
    """성분 식별 결과 한 건."""

    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    ingredient_code: int
    canonical_name: str = Field(min_length=1)
    standard_name_en: str | None = None
    old_names_ko: list[str] = Field(default_factory=list)
    old_names_en: list[str] = Field(default_factory=list)
    source_version: str = Field(min_length=1)


class AgentIngredientReadRepository:
    """표준명·정규화명·구명칭의 정확 일치 결과만 반환한다."""

    MAX_AMBIGUOUS_CANDIDATES: ClassVar[int] = 5
    _LOOKUP_SQL: ClassVar[str] = """
        SELECT
            id AS ingredient_id,
            ingredient_code,
            standard_name_ko AS canonical_name,
            standard_name_en,
            old_names_ko,
            old_names_en,
            source_version
        FROM ingredient_master
        WHERE lower(standard_name_ko) = lower(:name)
           OR lower(COALESCE(standard_name_en, '')) = lower(:name)
           OR lower(normalized_name_ko) = lower(:name)
           OR lower(COALESCE(normalized_name_en, '')) = lower(:name)
           OR EXISTS (
                SELECT 1 FROM unnest(old_names_ko) AS old_name
                WHERE lower(old_name) = lower(:name)
           )
           OR EXISTS (
                SELECT 1 FROM unnest(old_names_en) AS old_name
                WHERE lower(old_name) = lower(:name)
           )
        ORDER BY standard_name_ko, id
        LIMIT :limit
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_exact(self, name: str) -> list[IngredientLookupRow]:
        result = await self._session.execute(
            text(self._LOOKUP_SQL),
            {"name": name, "limit": self.MAX_AMBIGUOUS_CANDIDATES},
        )
        return [IngredientLookupRow.model_validate(row) for row in result.mappings().all()]
