"""`mfds_evidence_embedding_pipeline`이 주고받는 Pydantic 모델."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MfdsEvidenceEmbeddingFailure(BaseModel):
    """embedding/insert 중 실패한 chunk 한 건. 배치 하나가 실패해도 이 단위로
    격리해 나머지 배치 처리를 계속할 수 있게 한다."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    legacy_evidence_id: UUID
    reason: str
    retryable: bool


class MfdsEvidenceEmbeddingSummary(BaseModel):
    """임베딩 실행 결과 요약."""

    model_config = ConfigDict(frozen=True)

    dry_run: bool
    total_staged: int
    documents_missing: int
    already_embedded_skipped: int
    embedded_now: int
    failed: int
