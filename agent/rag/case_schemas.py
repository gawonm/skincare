"""NIA Case 검색과 rerank 결과를 저장소 구현과 분리한 Agent 계약."""

from enum import StrEnum
from typing import Self

from pydantic import Field, FiniteFloat, model_validator

from agent.rag.schemas import EmbeddingVector, LookupStatus, RagModel

DEFAULT_CASE_CANDIDATE_LIMIT = 20
DEFAULT_CASE_RERANK_LIMIT = 3


class CaseDatasetSplit(StrEnum):
    TRAINING = "training"
    VALIDATION = "validation"


class CaseProvenance(RagModel):
    archive_name: str = Field(min_length=1)
    member_name: str | None = Field(default=None, min_length=1)
    line_number: int = Field(ge=1)


class CaseMetadata(RagModel):
    target_concern: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)


class CaseSearchRequest(RagModel):
    query: str = Field(min_length=1)
    query_embedding: EmbeddingVector
    text_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    candidate_limit: int = Field(default=DEFAULT_CASE_CANDIDATE_LIMIT, ge=3)


class CaseSearchHit(RagModel):
    case_id: str = Field(min_length=1)
    page_content: str = Field(min_length=1)
    text_version: str = Field(min_length=1)
    dataset_split: CaseDatasetSplit
    metadata: CaseMetadata
    provenance: CaseProvenance
    vector_similarity: FiniteFloat
    rerank_score: FiniteFloat | None = None


class CaseSearchResult(RagModel):
    status: LookupStatus
    hits: list[CaseSearchHit] = Field(default_factory=list)
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        if self.status is LookupStatus.SUCCESS and not self.hits:
            raise ValueError("SUCCESS Case 검색 결과에는 hit이 필요합니다.")
        if self.status is not LookupStatus.SUCCESS and self.hits:
            raise ValueError("성공하지 않은 Case 검색 결과에는 hit을 넣을 수 없습니다.")
        if self.status is LookupStatus.ERROR and not self.error_message:
            raise ValueError("ERROR Case 검색 결과에는 원인 메시지가 필요합니다.")
        return self


class CaseRerankRequest(RagModel):
    query: str = Field(min_length=1)
    candidates: list[CaseSearchHit] = Field(min_length=1)
    limit: int = Field(default=DEFAULT_CASE_RERANK_LIMIT, ge=1, le=DEFAULT_CASE_RERANK_LIMIT)


class CaseRerankResult(RagModel):
    model: str = Field(min_length=1)
    hits: list[CaseSearchHit] = Field(min_length=1, max_length=DEFAULT_CASE_RERANK_LIMIT)

    @model_validator(mode="after")
    def validate_rerank_scores(self) -> Self:
        if any(hit.rerank_score is None for hit in self.hits):
            raise ValueError("Case rerank 결과에는 모든 hit의 rerank_score가 필요합니다.")
        return self


class CaseBundle(RagModel):
    search: CaseSearchResult
    rerank: CaseRerankResult | None = None
    rerank_fallback_used: bool = False

    def selected_hits(self) -> list[CaseSearchHit]:
        if self.rerank is not None:
            return list(self.rerank.hits)
        if self.search.status is not LookupStatus.SUCCESS:
            return []
        return list(self.search.hits[:DEFAULT_CASE_RERANK_LIMIT])
