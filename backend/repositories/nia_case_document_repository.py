"""NIA 사례 검색 문서 저장 전용 Repository."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.nia_case_document import (
    NIA_CASE_EMBEDDING_DIMENSION,
    NiaCaseDatasetSplit,
    NiaCaseDocument,
)


class NiaCaseRepositoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NiaCaseExistingDigestRequest(NiaCaseRepositoryModel):
    case_ids: list[str] = Field(min_length=1)
    text_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)


class NiaCaseExistingDigest(NiaCaseRepositoryModel):
    case_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class NiaCaseDocumentUpsert(NiaCaseRepositoryModel):
    case_id: str = Field(min_length=1)
    dataset_split: NiaCaseDatasetSplit
    source_archive_name: str = Field(min_length=1)
    source_member_name: str | None = Field(default=None, min_length=1)
    source_line_number: int = Field(ge=1)
    page_content: str = Field(min_length=1)
    embedding_text: str = Field(min_length=1)
    text_version: str = Field(min_length=1)
    target_concern: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    skin_concerns: list[str]
    case_metadata: dict[str, Any]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding: list[FiniteFloat] = Field(
        min_length=NIA_CASE_EMBEDDING_DIMENSION,
        max_length=NIA_CASE_EMBEDDING_DIMENSION,
    )
    embedding_model: str = Field(min_length=1)


class NiaCaseDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_existing_digests(
        self, request: NiaCaseExistingDigestRequest
    ) -> list[NiaCaseExistingDigest]:
        statement = select(
            NiaCaseDocument.case_id,
            NiaCaseDocument.content_hash,
        ).where(
            NiaCaseDocument.case_id.in_(request.case_ids),
            NiaCaseDocument.text_version == request.text_version,
            NiaCaseDocument.embedding_model == request.embedding_model,
        )
        result = await self._session.execute(statement)
        return [
            NiaCaseExistingDigest(case_id=row.case_id, content_hash=row.content_hash)
            for row in result
        ]

    async def upsert_many(self, records: list[NiaCaseDocumentUpsert]) -> int:
        if not records:
            return 0

        table = NiaCaseDocument.__table__
        statement = insert(table).values([self._to_values(record) for record in records])
        statement = statement.on_conflict_do_update(
            constraint="uq_nia_case_document_case_text_model",
            set_={
                "dataset_split": statement.excluded.dataset_split,
                "source_archive_name": statement.excluded.source_archive_name,
                "source_member_name": statement.excluded.source_member_name,
                "source_line_number": statement.excluded.source_line_number,
                "page_content": statement.excluded.page_content,
                "embedding_text": statement.excluded.embedding_text,
                "target_concern": statement.excluded.target_concern,
                "gender": statement.excluded.gender,
                "age": statement.excluded.age,
                "skin_type": statement.excluded.skin_type,
                "skin_concerns": statement.excluded.skin_concerns,
                "metadata": statement.excluded.metadata,
                "content_hash": statement.excluded.content_hash,
                "embedding": statement.excluded.embedding,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)
        return len(records)

    def _to_values(self, record: NiaCaseDocumentUpsert) -> dict[str, Any]:
        return {
            "case_id": record.case_id,
            "dataset_split": record.dataset_split.value,
            "source_archive_name": record.source_archive_name,
            "source_member_name": record.source_member_name,
            "source_line_number": record.source_line_number,
            "page_content": record.page_content,
            "embedding_text": record.embedding_text,
            "text_version": record.text_version,
            "target_concern": record.target_concern,
            "gender": record.gender,
            "age": record.age,
            "skin_type": record.skin_type,
            "skin_concerns": record.skin_concerns,
            "metadata": record.case_metadata,
            "content_hash": record.content_hash,
            "embedding": list(record.embedding),
            "embedding_model": record.embedding_model,
        }
