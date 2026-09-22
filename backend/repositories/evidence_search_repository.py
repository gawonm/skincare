"""최신 2-Layer 저장소의 Evidence 검색 전용 읽기 Repository."""

from datetime import date, datetime
from typing import ClassVar
from uuid import UUID

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import ARRAY, String, Uuid, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause


class EvidenceSearchRow(BaseModel):
    """Evidence 청크와 문서·성분 메타데이터의 조회 결과."""

    model_config = ConfigDict(frozen=True)

    evidence_id: UUID
    source_id: str = Field(min_length=1)
    document_source_type: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    document_date: date | None = None
    document_url: str | None = None
    document_doi: str | None = None
    document_pmid: str | None = None
    jurisdiction: str | None = None
    evidence_level: str = Field(min_length=1)
    document_status: str | None = None
    study_type: str | None = None
    formulation_type: str | None = None
    claim_topics: list[str] = Field(default_factory=list)
    retrieved_at: datetime
    chunk_id: str = Field(min_length=1)
    chunk_source_type: str = Field(min_length=1)
    # PubMed 청크는 abstract가 있지만 MFDS 규제 청크는 section이 NULL이므로 None을 허용한다
    section: str | None = None
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    chunk_url: str | None = None
    chunk_doi: str | None = None
    chunk_pmid: str | None = None
    target_ids: list[UUID] = Field(min_length=1)
    score: FiniteFloat


class EvidenceVectorSearchRequest(BaseModel):
    """Evidence vector 조회 입력."""

    model_config = ConfigDict(frozen=True)

    query_vector: list[float] = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    target_ids: list[UUID] = Field(default_factory=list)
    source_types: list[str] | None = None
    limit: int = Field(ge=1)


class EvidenceTextSearchRequest(BaseModel):
    """Evidence 텍스트 조회 입력."""

    model_config = ConfigDict(frozen=True)

    query_text: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    target_ids: list[UUID] = Field(default_factory=list)
    source_types: list[str] | None = None
    limit: int = Field(ge=1)


class EvidenceSearchRepository:
    """`evidence_document`/`evidence_chunk`/성분 연결을 청크 단위로 조회한다."""

    EMBEDDING_DIMENSIONS: ClassVar[int] = 1024
    _BASE_COLUMNS: ClassVar[str] = """
        evidence_chunk.id AS evidence_id,
        evidence_document.source_id,
        evidence_document.source_type AS document_source_type,
        evidence_document.source_title,
        evidence_document.document_date,
        evidence_document.url AS document_url,
        evidence_document.doi AS document_doi,
        evidence_document.pmid AS document_pmid,
        evidence_document.jurisdiction,
        evidence_document.evidence_level,
        evidence_document.document_status,
        evidence_document.study_type,
        evidence_document.formulation_type,
        evidence_document.claim_topics,
        evidence_document.retrieved_at,
        evidence_chunk.chunk_id,
        evidence_chunk.source_type AS chunk_source_type,
        evidence_chunk.section,
        evidence_chunk.chunk_index,
        evidence_chunk.content,
        evidence_chunk.url AS chunk_url,
        evidence_chunk.doi AS chunk_doi,
        evidence_chunk.pmid AS chunk_pmid,
        ARRAY(
            SELECT DISTINCT link.ingredient_id
            FROM evidence_chunk_ingredient AS link
            WHERE link.evidence_chunk_id = evidence_chunk.id
            ORDER BY link.ingredient_id
        ) AS target_ids
    """
    _TARGET_FILTER: ClassVar[str] = """
        EXISTS (
            SELECT 1
            FROM evidence_chunk_ingredient AS target_link
            WHERE target_link.evidence_chunk_id = evidence_chunk.id
              AND target_link.ingredient_id = ANY(:target_ids)
        )
    """
    _SOURCE_FILTER: ClassVar[str] = """
        (:source_types IS NULL OR evidence_document.source_type = ANY(:source_types))
    """
    _VECTOR_SQL: ClassVar[str] = f"""
        SELECT
            {_BASE_COLUMNS},
            1 - (evidence_chunk.embedding <=> :query_vector) AS score
        FROM evidence_chunk
        JOIN evidence_document ON evidence_document.id = evidence_chunk.document_id
        WHERE evidence_chunk.embedding_model = :embedding_model
          AND {_SOURCE_FILTER}
        ORDER BY evidence_chunk.embedding <=> :query_vector, evidence_chunk.chunk_id
        LIMIT :limit
    """
    _TARGETED_VECTOR_SQL: ClassVar[str] = f"""
        WITH target_evidence_chunk AS MATERIALIZED (
            SELECT evidence_chunk.*
            FROM evidence_chunk
            WHERE evidence_chunk.embedding_model = :embedding_model
              AND {_TARGET_FILTER}
        )
        SELECT
            {_BASE_COLUMNS},
            1 - (evidence_chunk.embedding <=> :query_vector) AS score
        FROM target_evidence_chunk AS evidence_chunk
        JOIN evidence_document ON evidence_document.id = evidence_chunk.document_id
        WHERE {_SOURCE_FILTER}
        ORDER BY evidence_chunk.embedding <=> :query_vector, evidence_chunk.chunk_id
        LIMIT :limit
    """
    _TEXT_SQL: ClassVar[str] = f"""
        SELECT
            {_BASE_COLUMNS},
            ts_rank_cd(
                to_tsvector('simple', evidence_chunk.content),
                plainto_tsquery('simple', :query_text)
            ) AS score
        FROM evidence_chunk
        JOIN evidence_document ON evidence_document.id = evidence_chunk.document_id
        WHERE evidence_chunk.embedding_model = :embedding_model
          AND {_SOURCE_FILTER}
          AND to_tsvector('simple', evidence_chunk.content)
              @@ plainto_tsquery('simple', :query_text)
        ORDER BY score DESC, evidence_chunk.chunk_id
        LIMIT :limit
    """
    _TARGETED_TEXT_SQL: ClassVar[str] = f"""
        SELECT
            {_BASE_COLUMNS},
            ts_rank_cd(
                to_tsvector('simple', evidence_chunk.content),
                plainto_tsquery('simple', :query_text)
            ) AS score
        FROM evidence_chunk
        JOIN evidence_document ON evidence_document.id = evidence_chunk.document_id
        WHERE evidence_chunk.embedding_model = :embedding_model
          AND {_TARGET_FILTER}
          AND {_SOURCE_FILTER}
          AND to_tsvector('simple', evidence_chunk.content)
              @@ plainto_tsquery('simple', :query_text)
        ORDER BY score DESC, evidence_chunk.chunk_id
        LIMIT :limit
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_by_vector(
        self, request: EvidenceVectorSearchRequest
    ) -> list[EvidenceSearchRow]:
        if len(request.query_vector) != self.EMBEDDING_DIMENSIONS:
            raise ValueError(
                "Evidence 질의 벡터 차원이 BGE-M3 저장 벡터와 다릅니다: "
                f"expected={self.EMBEDDING_DIMENSIONS}, actual={len(request.query_vector)}"
            )
        sql = self._TARGETED_VECTOR_SQL if request.target_ids else self._VECTOR_SQL
        statement = self._statement(sql, binds_target_ids=bool(request.target_ids)).bindparams(
            bindparam("query_vector", type_=Vector(self.EMBEDDING_DIMENSIONS))
        )
        return await self._execute(
            statement,
            {
                "query_vector": request.query_vector,
                "embedding_model": request.embedding_model,
                "target_ids": request.target_ids,
                "source_types": request.source_types,
                "limit": request.limit,
            },
        )

    async def search_by_text(
        self, request: EvidenceTextSearchRequest
    ) -> list[EvidenceSearchRow]:
        sql = self._TARGETED_TEXT_SQL if request.target_ids else self._TEXT_SQL
        return await self._execute(
            self._statement(sql, binds_target_ids=bool(request.target_ids)),
            {
                "query_text": request.query_text,
                "embedding_model": request.embedding_model,
                "target_ids": request.target_ids,
                "source_types": request.source_types,
                "limit": request.limit,
            },
        )

    def _statement(self, sql: str, *, binds_target_ids: bool) -> TextClause:
        statement = text(sql).bindparams(
            bindparam("source_types", type_=ARRAY(String()))
        )
        if not binds_target_ids:
            return statement
        # HNSW가 전체 후보를 먼저 제한하면 희소한 성분 Evidence가 탈락하므로,
        # 성분 지정 검색은 materialized 후보 집합에서 정확한 거리 순서를 계산한다.
        return statement.bindparams(
            bindparam("target_ids", type_=ARRAY(Uuid(as_uuid=True)))
        )

    async def _execute(
        self,
        statement: TextClause,
        parameters: dict[str, object],
    ) -> list[EvidenceSearchRow]:
        result = await self._session.execute(statement, parameters)
        return [EvidenceSearchRow.model_validate(row) for row in result.mappings().all()]
