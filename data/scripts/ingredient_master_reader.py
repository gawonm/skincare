"""`IngredientMaster` 전체 조회. `models/`는 data 파트 소유이므로 backend/repositories를
건드리지 않고 여기서 직접 쿼리한다(`kcia_ingredient_importer.py`와 같은 관례).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingredient import IngredientMaster


class IngredientMasterReader:
    """`IngredientMaster` 조회 전용. commit은 하지 않는다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[IngredientMaster]:
        result = await self._session.execute(select(IngredientMaster))
        return list(result.scalars().all())
