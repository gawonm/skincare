"""`Evidence` 테이블 조회. RAG 적재 파이프라인이 근거 소스로 읽어간다."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.evidence import Evidence


class EvidenceRepository:
    """`Evidence` 조회 전용. commit은 하지 않는다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Evidence]:
        result = await self._session.execute(select(Evidence))
        return list(result.scalars().all())

    async def list_by_ingredient(self, ingredient_id: UUID) -> list[Evidence]:
        result = await self._session.execute(
            select(Evidence).where(Evidence.ingredient_id == ingredient_id)
        )
        return list(result.scalars().all())

    async def list_by_ids(self, evidence_ids: list[UUID]) -> list[Evidence]:
        if not evidence_ids:
            return []
        result = await self._session.execute(select(Evidence).where(Evidence.id.in_(evidence_ids)))
        return list(result.scalars().all())
