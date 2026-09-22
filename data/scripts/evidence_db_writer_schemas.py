"""FINAL_EVIDENCE_DB_ACTION_PLAN을 실제 `evidence_document`/`evidence_chunk`/
`evidence_chunk_ingredient`에 반영하는 write 단계가 주고받는 Pydantic 모델."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from models.evidence_document import (
    EvidenceClaimTopic,
    EvidenceDocumentSourceType,
    EvidenceDocumentStatus,
    EvidenceFormulationType,
    EvidenceLevel,
    EvidenceStudyType,
)


class BundleDocumentRecord(BaseModel):
    """`combined_evidence_documents.jsonl` 한 행(INSERT 대상만 이 모델로 적재)."""

    model_config = ConfigDict(frozen=True)

    source_type: EvidenceDocumentSourceType
    source_id: str
    source_title: str
    publisher: str | None
    document_date: date | None
    url: str | None
    doi: str | None
    pmid: str | None
    language: str
    evidence_level: EvidenceLevel
    raw_ingredient_names: list[str]
    document_status: EvidenceDocumentStatus | None
    study_type: EvidenceStudyType | None
    formulation_type: EvidenceFormulationType | None
    claim_topics: list[EvidenceClaimTopic]
    retrieved_at: datetime


class BundleChunkRecord(BaseModel):
    """`combined_evidence_chunks.jsonl` 한 행(INSERT/REPLACE 대상만 이 모델로 적재)."""

    model_config = ConfigDict(frozen=True)

    document_source_id: str
    chunk_id: str
    source_type: EvidenceDocumentSourceType
    source_title: str
    page: int | None
    section: str | None
    chunk_index: int
    content: str
    content_hash: str
    parser_version: str
    url: str | None
    doi: str | None
    pmid: str | None
    evidence_level: EvidenceLevel


class EmbeddingVector(BaseModel):
    """`evidence_embeddings.jsonl` 한 행."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    model: str
    dimension: int
    content_hash: str
    vector: list[float]


class LinkAction(BaseModel):
    """`evidence_db_load_plan_links.csv`의 `action=INSERT` 또는 `REMOVE` 한 행."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    ingredient_id: UUID
    action: str


class WriteTransactionSummary(BaseModel):
    """write 트랜잭션이 실제로 반영한 건수."""

    model_config = ConfigDict(frozen=True)

    documents_inserted: int
    documents_removed: int
    chunks_inserted: int
    chunks_replaced: int
    chunks_removed: int
    links_inserted: int
    links_removed: int
