"""Claim statement 청크를 document 입력과 정확히 동기화하는 Repository."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.claim_chunk import (
    CLAIM_EMBEDDING_DIMENSION,
    ClaimChunk,
    ClaimIngestionDecision,
    ClaimPriority,
    ClaimStatementType,
    ClaimSupportStatus,
)


class ClaimChunkRepositoryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ClaimSourceSpanValue(ClaimChunkRepositoryModel):
    json_path: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class ClaimChunkUpsert(ClaimChunkRepositoryModel):
    statement_id: str = Field(min_length=1)
    statement_type: ClaimStatementType
    content: str = Field(min_length=1)
    source_spans: list[ClaimSourceSpanValue] = Field(min_length=1)
    decision: ClaimIngestionDecision
    priority: ClaimPriority
    support_status: ClaimSupportStatus
    embedding: list[FiniteFloat] = Field(
        min_length=CLAIM_EMBEDDING_DIMENSION,
        max_length=CLAIM_EMBEDDING_DIMENSION,
    )
    embedding_model: str = Field(min_length=1)


class ClaimChunkIdentity(ClaimChunkRepositoryModel):
    id: UUID
    statement_id: str = Field(min_length=1)


class ClaimChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sync_document(
        self, claim_document_id: UUID, records: list[ClaimChunkUpsert]
    ) -> list[ClaimChunkIdentity]:
        statement_ids = [record.statement_id for record in records]
        delete_statement = delete(ClaimChunk).where(
            ClaimChunk.claim_document_id == claim_document_id
        )
        if statement_ids:
            delete_statement = delete_statement.where(ClaimChunk.statement_id.not_in(statement_ids))
        await self._session.execute(delete_statement)
        if not records:
            return []

        table = ClaimChunk.__table__
        insert_statement = insert(table).values(
            [self._to_values(claim_document_id, record) for record in records]
        )
        insert_statement = insert_statement.on_conflict_do_update(
            constraint="uq_claim_chunk_document_statement",
            set_={
                "statement_type": insert_statement.excluded.statement_type,
                "content": insert_statement.excluded.content,
                "source_spans": insert_statement.excluded.source_spans,
                "decision": insert_statement.excluded.decision,
                "priority": insert_statement.excluded.priority,
                "support_status": insert_statement.excluded.support_status,
                "embedding": insert_statement.excluded.embedding,
                "embedding_model": insert_statement.excluded.embedding_model,
                "updated_at": func.now(),
            },
        ).returning(table.c.id, table.c.statement_id)
        rows = (await self._session.execute(insert_statement)).all()
        return [ClaimChunkIdentity(id=row.id, statement_id=row.statement_id) for row in rows]

    def _to_values(self, document_id: UUID, record: ClaimChunkUpsert) -> dict[str, Any]:
        return {
            "claim_document_id": document_id,
            "statement_id": record.statement_id,
            "statement_type": record.statement_type.value,
            "content": record.content,
            "source_spans": [span.model_dump(mode="json") for span in record.source_spans],
            "decision": record.decision.value,
            "priority": record.priority.value,
            "support_status": record.support_status.value,
            "embedding": list(record.embedding),
            "embedding_model": record.embedding_model,
        }
