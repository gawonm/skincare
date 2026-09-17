"""legacy `evidence`(MFDS 8,288건)를 `evidence_document`/`evidence_chunk`로 변환하는
백필 파이프라인이 주고받는 Pydantic 모델.

`evidence_chunk.embedding`은 `vector(1024) NOT NULL`이라 이번 단계(임베딩 미실행)에서는
`EvidenceChunk` ORM 행을 직접 만들 수 없다. 그래서 embedding을 제외한 필드만 담는
`EvidenceChunkStagingRecord`를 중간 산출물로 두고, 실제 `evidence_chunk` INSERT는 이후
임베딩 단계 스크립트가 이 산출물을 읽어 수행한다.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from models.evidence_document import EvidenceClaimTopic, EvidenceDocumentSourceType, EvidenceLevel


class LegacyEvidenceRow(BaseModel):
    """legacy `evidence` 테이블 한 행. SQLAlchemy Row를 매퍼 입력으로 바로 안 쓰고
    이 모델로 감싸 매퍼가 DB 세션/컬럼 순서에 의존하지 않게 한다."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    ingredient_id: UUID
    claim: str
    conditions: str | None
    jurisdiction: str
    regulate_type: str | None
    cas_no: str | None
    ingredient_synonym: str | None
    notice_ingredient_name: str | None
    source_title: str
    source_url: str
    collected_at: datetime


class EvidenceDocumentPlan(BaseModel):
    """jurisdiction 하나에 대응하는 `evidence_document` 적재 계획 한 건."""

    model_config = ConfigDict(frozen=True)

    source_type: EvidenceDocumentSourceType
    source_id: str
    source_title: str
    url: str | None
    jurisdiction: str
    language: str
    evidence_level: EvidenceLevel
    raw_ingredient_names: list[str]
    claim_topics: list[EvidenceClaimTopic]
    retrieved_at: datetime
    legacy_evidence_ids: list[UUID]


class EvidenceChunkStagingRecord(BaseModel):
    """`evidence_chunk` INSERT 직전까지의 값. `embedding`/`embedding_model`만 없다."""

    model_config = ConfigDict(frozen=True)

    document_source_id: str
    chunk_id: str
    source_type: EvidenceDocumentSourceType
    source_title: str
    chunk_index: int
    content: str
    content_hash: str
    parser_version: str
    url: str | None
    jurisdiction: str
    evidence_level: EvidenceLevel
    legacy_evidence_id: UUID
    ingredient_id: UUID


class MfdsEvidenceBackfillFailure(BaseModel):
    """변환에 실패한 legacy row 한 건."""

    model_config = ConfigDict(frozen=True)

    legacy_evidence_id: UUID
    reason: str


class MfdsEvidenceBackfillSummary(BaseModel):
    """백필 실행 결과 요약."""

    model_config = ConfigDict(frozen=True)

    dry_run: bool
    total_legacy_rows: int
    documents_planned: int
    chunks_planned: int
    failures: int
    documents_inserted: int
    documents_already_existed: int
