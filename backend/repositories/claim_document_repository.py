"""Claim 원본 document 단위 저장 Repository."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.claim_document import ClaimDatasetSplit, ClaimDocument


class ClaimDocumentRepositoryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ClaimDocumentUpsert(ClaimDocumentRepositoryModel):
    source_record_id: str = Field(min_length=1)
    annotation_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    dataset_split: ClaimDatasetSplit
    skin_concerns_raw: list[str]
    production_ready: bool


class ClaimDocumentIdentity(ClaimDocumentRepositoryModel):
    id: UUID
    source_record_id: str = Field(min_length=1)


class ClaimDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, record: ClaimDocumentUpsert) -> ClaimDocumentIdentity:
        table = ClaimDocument.__table__
        statement = insert(table).values(
            source_record_id=record.source_record_id,
            annotation_version=record.annotation_version,
            schema_version=record.schema_version,
            dataset_split=record.dataset_split.value,
            skin_concerns_raw=record.skin_concerns_raw,
            production_ready=record.production_ready,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_claim_document_record_annotation",
            set_={
                "schema_version": statement.excluded.schema_version,
                "dataset_split": statement.excluded.dataset_split,
                "skin_concerns_raw": statement.excluded.skin_concerns_raw,
                "production_ready": statement.excluded.production_ready,
                "updated_at": func.now(),
            },
        ).returning(table.c.id, table.c.source_record_id)
        row = (await self._session.execute(statement)).one()
        return ClaimDocumentIdentity(id=row.id, source_record_id=row.source_record_id)
