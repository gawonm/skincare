"""최신 2-Layer 저장소의 Claim 검색 전용 읽기 Repository."""

from typing import ClassVar
from uuid import UUID

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import ARRAY, Text, Uuid, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from models.claim_chunk import (
    ClaimIngestionDecision,
    ClaimIngredientMatchingStatus,
    ClaimIngredientRefRole,
    ClaimStatementType,
    ClaimSupportStatus,
)


class ClaimIngredientRow(BaseModel):
    """Claim statement에 연결된 성분 한 건."""

    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID | None = None
    raw_name: str = Field(min_length=1)
    matching_status: ClaimIngredientMatchingStatus
    role: ClaimIngredientRefRole


class ClaimSearchRow(BaseModel):
    """Claim 검색 SQL 결과. Agent DTO로의 의미 변환은 service가 담당한다."""

    model_config = ConfigDict(frozen=True)

    claim_chunk_id: UUID
    source_record_id: str = Field(min_length=1)
    annotation_version: str = Field(min_length=1)
    statement_id: str = Field(min_length=1)
    statement_type: ClaimStatementType
    content: str = Field(min_length=1)
    decision: ClaimIngestionDecision
    support_status: ClaimSupportStatus
    ingredients: list[ClaimIngredientRow] = Field(min_length=1)
    retrieval_score: FiniteFloat


class ClaimVectorSearchRequest(BaseModel):
    """Claim vector 조회 입력."""

    model_config = ConfigDict(frozen=True)

    query_vector: list[float] = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    annotation_version: str = Field(min_length=1)
    statement_types: list[ClaimStatementType] = Field(min_length=1)
    ingredient_ids: list[UUID] = Field(default_factory=list)
    limit: int = Field(ge=1)


class ClaimSearchRepository:
    """`claim_document`/`claim_chunk`/성분 연결을 statement 단위로 조회한다."""

    EMBEDDING_DIMENSIONS: ClassVar[int] = 1024
    INGESTIBLE_DECISION_PREFIX: ClassVar[str] = "ingestible_"
    SUPPORTED_STATEMENT_TYPES: ClassVar[tuple[ClaimStatementType, ...]] = (
        ClaimStatementType.INGREDIENT_EFFECT_CLAIM,
        ClaimStatementType.USAGE_INSTRUCTION,
        ClaimStatementType.COMBINATION_CLAIM,
    )
    REJECTED_MATCHING_STATUS: ClassVar[ClaimIngredientMatchingStatus] = (
        ClaimIngredientMatchingStatus.REJECTED
    )
    _VECTOR_SQL: ClassVar[str] = """
        WITH ranked_claim AS (
            SELECT
                cd.source_record_id,
                cd.annotation_version,
                cc.id AS claim_chunk_id,
                cc.statement_id,
                cc.statement_type,
                cc.content,
                cc.decision,
                cc.support_status,
                1 - (cc.embedding <=> :query_vector) AS retrieval_score
            FROM claim_chunk AS cc
            JOIN claim_document AS cd ON cd.id = cc.claim_document_id
            WHERE cc.embedding_model = :embedding_model
              AND cd.annotation_version = :annotation_version
              AND left(cc.decision, length(:decision_prefix)) = :decision_prefix
              AND cc.statement_type = ANY(:statement_types)
              AND (
                  :has_ingredient_filter = false
                  OR EXISTS (
                      SELECT 1
                      FROM claim_chunk_ingredient AS filter_ingredient
                      WHERE filter_ingredient.claim_chunk_id = cc.id
                        AND filter_ingredient.matching_status = :matched_status
                        AND filter_ingredient.ingredient_id = ANY(:ingredient_ids)
                  )
              )
            ORDER BY cc.embedding <=> :query_vector, cc.statement_id
            LIMIT :limit
        )
        SELECT
            ranked_claim.claim_chunk_id,
            ranked_claim.source_record_id,
            ranked_claim.annotation_version,
            ranked_claim.statement_id,
            ranked_claim.statement_type,
            ranked_claim.content,
            ranked_claim.decision,
            ranked_claim.support_status,
            jsonb_agg(
                jsonb_build_object(
                    'ingredient_id', claim_ingredient.ingredient_id,
                    'raw_name', claim_ingredient.raw_name,
                    'matching_status', claim_ingredient.matching_status,
                    'role', claim_ingredient.role
                )
                ORDER BY claim_ingredient.raw_name, claim_ingredient.id
            ) AS ingredients,
            ranked_claim.retrieval_score
        FROM ranked_claim
        JOIN claim_chunk_ingredient AS claim_ingredient
          ON claim_ingredient.claim_chunk_id = ranked_claim.claim_chunk_id
         AND claim_ingredient.matching_status <> :rejected_status
        GROUP BY
            ranked_claim.claim_chunk_id,
            ranked_claim.source_record_id,
            ranked_claim.annotation_version,
            ranked_claim.statement_id,
            ranked_claim.statement_type,
            ranked_claim.content,
            ranked_claim.decision,
            ranked_claim.support_status,
            ranked_claim.retrieval_score
        ORDER BY ranked_claim.retrieval_score DESC, ranked_claim.statement_id
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_by_vector(self, request: ClaimVectorSearchRequest) -> list[ClaimSearchRow]:
        if len(request.query_vector) != self.EMBEDDING_DIMENSIONS:
            raise ValueError(
                "Claim 질의 벡터 차원이 BGE-M3 저장 벡터와 다릅니다: "
                f"expected={self.EMBEDDING_DIMENSIONS}, actual={len(request.query_vector)}"
            )
        statement = self._statement().bindparams(
            bindparam("query_vector", type_=Vector(self.EMBEDDING_DIMENSIONS)),
            bindparam("statement_types", type_=ARRAY(Text())),
            bindparam("ingredient_ids", type_=ARRAY(Uuid(as_uuid=True))),
        )
        result = await self._session.execute(
            statement,
            {
                "query_vector": request.query_vector,
                "embedding_model": request.embedding_model,
                "annotation_version": request.annotation_version,
                "decision_prefix": self.INGESTIBLE_DECISION_PREFIX,
                "statement_types": [
                    statement_type.value for statement_type in request.statement_types
                ],
                "ingredient_ids": request.ingredient_ids,
                "has_ingredient_filter": bool(request.ingredient_ids),
                "matched_status": ClaimIngredientMatchingStatus.MATCHED.value,
                "rejected_status": self.REJECTED_MATCHING_STATUS.value,
                "limit": request.limit,
            },
        )
        return [ClaimSearchRow.model_validate(row) for row in result.mappings().all()]

    def _statement(self) -> TextClause:
        return text(self._VECTOR_SQL)
