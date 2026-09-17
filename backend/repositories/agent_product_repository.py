"""Agent 상품 검색 포트용 Product/confirmed 성분 연결 읽기 Repository."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ARRAY, Uuid, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


class AgentProductRow(BaseModel):
    """상품과 confirmed 성분 목록의 조회 결과 한 건."""

    model_config = ConfigDict(frozen=True)

    product_id: UUID
    source: str = Field(min_length=1)
    source_product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    observed_at: datetime
    ingredient_ids: list[UUID] = Field(min_length=1)


class AgentProductReadRepository:
    """확정된 전성분 연결만 사용해 상품을 조회하고 product ID로 중복을 제거한다."""

    CONFIRMED_ACCEPTANCE: ClassVar[str] = "confirmed"
    _SEARCH_SQL: ClassVar[str] = """
        WITH matching_products AS (
            SELECT
                product.id,
                count(DISTINCT matched_token.ingredient_id) AS matched_ingredient_count
            FROM product
            JOIN product_ingredient_snapshot AS matched_snapshot
              ON matched_snapshot.source = product.source
             AND matched_snapshot.source_product_id = product.source_product_id
            JOIN product_ingredient AS matched_token
              ON matched_token.snapshot_id = matched_snapshot.id
             AND matched_token.match_acceptance = :confirmed_acceptance
             AND matched_token.ingredient_id IS NOT NULL
            WHERE matched_token.ingredient_id = ANY(:ingredient_ids)
            GROUP BY product.id
            ORDER BY matched_ingredient_count DESC, product.id
            LIMIT :limit
        )
        SELECT
            product.id AS product_id,
            product.source,
            product.source_product_id,
            product.display_title AS name,
            COALESCE(
                product.service_category::text,
                product.product_type_normalized::text,
                product.category1
            ) AS category,
            product.observed_at,
            ARRAY(
                SELECT DISTINCT confirmed_token.ingredient_id
                FROM product_ingredient_snapshot AS confirmed_snapshot
                JOIN product_ingredient AS confirmed_token
                  ON confirmed_token.snapshot_id = confirmed_snapshot.id
                 AND confirmed_token.match_acceptance = :confirmed_acceptance
                 AND confirmed_token.ingredient_id IS NOT NULL
                WHERE confirmed_snapshot.source = product.source
                  AND confirmed_snapshot.source_product_id = product.source_product_id
                ORDER BY confirmed_token.ingredient_id
            ) AS ingredient_ids
        FROM matching_products
        JOIN product ON product.id = matching_products.id
        ORDER BY matching_products.matched_ingredient_count DESC, product.id
    """
    _GET_SQL: ClassVar[str] = """
        SELECT
            product.id AS product_id,
            product.source,
            product.source_product_id,
            product.display_title AS name,
            COALESCE(
                product.service_category::text,
                product.product_type_normalized::text,
                product.category1
            ) AS category,
            product.observed_at,
            ARRAY(
                SELECT DISTINCT confirmed_token.ingredient_id
                FROM product_ingredient_snapshot AS confirmed_snapshot
                JOIN product_ingredient AS confirmed_token
                  ON confirmed_token.snapshot_id = confirmed_snapshot.id
                 AND confirmed_token.match_acceptance = :confirmed_acceptance
                 AND confirmed_token.ingredient_id IS NOT NULL
                WHERE confirmed_snapshot.source = product.source
                  AND confirmed_snapshot.source_product_id = product.source_product_id
                ORDER BY confirmed_token.ingredient_id
            ) AS ingredient_ids
        FROM product
        WHERE product.id = :product_id
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_by_ingredients(
        self, ingredient_ids: list[UUID], limit: int
    ) -> list[AgentProductRow]:
        statement = text(self._SEARCH_SQL).bindparams(
            bindparam("ingredient_ids", type_=ARRAY(Uuid(as_uuid=True)))
        )
        result = await self._session.execute(
            statement,
            {
                "ingredient_ids": ingredient_ids,
                "confirmed_acceptance": self.CONFIRMED_ACCEPTANCE,
                "limit": limit,
            },
        )
        return [AgentProductRow.model_validate(row) for row in result.mappings().all()]

    async def get(self, product_id: UUID) -> AgentProductRow | None:
        result = await self._session.execute(
            text(self._GET_SQL),
            {
                "product_id": product_id,
                "confirmed_acceptance": self.CONFIRMED_ACCEPTANCE,
            },
        )
        row = result.mappings().one_or_none()
        if row is None or not row["ingredient_ids"]:
            return None
        return AgentProductRow.model_validate(row)
