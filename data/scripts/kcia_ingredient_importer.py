"""`KciaIngredientRow` 목록을 `IngredientMaster` 테이블에 적재한다.

`ingredient_code` 기준으로 upsert 한다. 같은 PDF를 새 버전으로 다시 실행해도
안전하게 재실행할 수 있어야 하기 때문이다.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.ingredient_schemas import IngredientImportSummary, KciaIngredientRow
from models.ingredient import IngredientMaster


class KciaIngredientImporter:
    """`IngredientMaster` upsert 담당. commit 은 호출한 쪽에서 한다."""

    def __init__(self, session: AsyncSession, normalizer: IngredientNameNormalizer) -> None:
        self._session = session
        self._normalizer = normalizer

    async def import_rows(
        self, rows: list[KciaIngredientRow], source_version: str
    ) -> IngredientImportSummary:
        inserted = 0
        updated = 0
        for row in rows:
            if await self._upsert(row, source_version):
                inserted += 1
            else:
                updated += 1

        return IngredientImportSummary(
            total_rows=len(rows),
            inserted=inserted,
            updated=updated,
            skipped_invalid_rows=0,
        )

    async def _upsert(self, row: KciaIngredientRow, source_version: str) -> bool:
        """행 하나를 upsert 하고, 신규 삽입이면 True 를 반환한다.

        `created_at` 과 `updated_at` 은 둘 다 `func.now()` 기본값을 쓰는데, PostgreSQL
        에서 같은 트랜잭션 안의 `now()` 는 항상 같은 값을 돌려준다. 그래서 삽입 직후에는
        두 값이 같고, 갱신 시에는 SET 절에서 `updated_at` 만 새 `now()` 로 바꿔 서로
        달라지게 만들어 삽입/갱신을 구분한다.
        """
        values = {
            "ingredient_code": row.ingredient_code,
            "standard_name_ko": row.standard_name_ko,
            "standard_name_en": row.standard_name_en,
            "old_names_ko": list(row.old_names_ko),
            "old_names_en": list(row.old_names_en),
            "normalized_name_ko": self._normalizer.normalize_ko(row.standard_name_ko),
            "normalized_name_en": self._normalizer.normalize_en(row.standard_name_en),
            "source_version": source_version,
        }
        update_values = {**values, "updated_at": func.now()}
        del update_values["ingredient_code"]

        statement = (
            insert(IngredientMaster)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_ingredient_master_ingredient_code",
                set_=update_values,
            )
            .returning(IngredientMaster.created_at, IngredientMaster.updated_at)
        )
        created_at, updated_at = (await self._session.execute(statement)).one()
        return created_at == updated_at
