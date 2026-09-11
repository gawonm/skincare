"""`IngredientKnowledgeFact` 테이블 조회. RAG 적재 파이프라인이 근거 소스로 읽어간다."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingredient_knowledge import IngredientKnowledgeFact


class IngredientKnowledgeFactRepository:
    """`IngredientKnowledgeFact` 조회 전용. commit은 하지 않는다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[IngredientKnowledgeFact]:
        result = await self._session.execute(select(IngredientKnowledgeFact))
        return list(result.scalars().all())

    async def list_by_ingredient(self, ingredient_id: UUID) -> list[IngredientKnowledgeFact]:
        result = await self._session.execute(
            select(IngredientKnowledgeFact).where(
                IngredientKnowledgeFact.ingredient_id == ingredient_id
            )
        )
        return list(result.scalars().all())

    async def list_by_ids(self, fact_ids: list[UUID]) -> list[IngredientKnowledgeFact]:
        if not fact_ids:
            return []
        result = await self._session.execute(
            select(IngredientKnowledgeFact).where(IngredientKnowledgeFact.id.in_(fact_ids))
        )
        return list(result.scalars().all())
