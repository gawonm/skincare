"""production Evidence retriever 평가가 주고받는 Pydantic 모델과 고정 테스트 케이스."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TargetMode(StrEnum):
    """이 케이스가 target_ids를 어떻게 정하는지."""

    SINGLE = "single"  # 이름 하나 -> ingredient_id 하나를 target_ids에 고정
    AMBIGUOUS_FAMILY = "ambiguous_family"  # CommonIngredientAliasMapper가 모호 판정하는 케이스
    ZERO_EVIDENCE = "zero_evidence"  # ingredient_master에는 있지만 evidence link가 0건인 성분


class FailureClassification(StrEnum):
    NONE = "none"
    DATA = "data"
    AGENT_RETRIEVAL = "agent-retrieval"
    BACKEND_REPOSITORY = "backend-repository"
    UNKNOWN = "unknown"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class EvalCase(BaseModel):
    """평가 케이스 하나의 고정 입력."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    target_mode: TargetMode
    expected_ingredient_name: str | None = None
    expected_source_types: list[str] = Field(default_factory=list)
    expected_claim_topics: list[str] = Field(default_factory=list)
    forbidden_ingredient_names: list[str] = Field(default_factory=list)
    notes: str = ""


class RetrievedChunkSummary(BaseModel):
    """평가용으로 얇게 뽑은 top-K 한 행."""

    model_config = ConfigDict(frozen=True)

    rank: int
    chunk_id: str
    source_type: str
    source_title: str
    pmid: str | None
    doi: str | None
    url: str | None
    locator: str
    claim_topics: list[str]
    target_ids: list[str]
    vector_similarity: float | None
    bm25_relevance: float | None
    reranker_score: float | None


class EvalCaseResult(BaseModel):
    """케이스 하나의 실행 결과 + 판정."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    query: str
    expected_ingredient_name: str | None
    expected_ingredient_id: str | None
    target_ids_used: list[str]
    lookup_status: str
    retrieved: list[RetrievedChunkSummary]
    ingredient_hit_at_3: bool
    ingredient_hit_at_5: bool
    ingredient_precision_at_5: float
    expected_source_hit_at_5: bool
    claim_topic_hit_at_5: bool
    forbidden_ingredient_hit_count: int
    citation_metadata_complete: bool
    zero_evidence_false_positive: bool
    verdict: Verdict
    failure_classification: FailureClassification
    reason: str
