"""`IngredientMaster` 조회. 성분명 매칭(`IngredientNameMatcher`)의 후보 소스로 쓴다."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from data.scripts.ingredient_schemas import IngredientCandidate
from models.ingredient import IngredientMaster


class IngredientMasterRepository:
    """`IngredientMaster` 조회 전용. commit은 하지 않는다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all_as_candidates(self) -> list[IngredientCandidate]:
        result = await self._session.execute(
            select(
                IngredientMaster.id,
                IngredientMaster.standard_name_ko,
                IngredientMaster.standard_name_en,
                IngredientMaster.old_names_ko,
                IngredientMaster.old_names_en,
                IngredientMaster.normalized_name_ko,
                IngredientMaster.normalized_name_en,
            )
        )
        return [
            IngredientCandidate(
                ingredient_id=row.id,
                standard_name_ko=row.standard_name_ko,
                standard_name_en=row.standard_name_en,
                old_names_ko=tuple(row.old_names_ko),
                old_names_en=tuple(row.old_names_en),
                normalized_name_ko=row.normalized_name_ko,
                normalized_name_en=row.normalized_name_en,
            )
            for row in result.all()
        ]
