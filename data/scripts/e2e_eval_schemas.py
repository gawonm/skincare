"""Notion "E2E 품질 평가 시나리오" 15개를 실제 ChatService로 실행하는 평가가
주고받는 Pydantic 모델."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FailureClassification(StrEnum):
    NONE = "none"
    DATA = "data"
    AGENT_RETRIEVAL = "agent-retrieval"
    AGENT_REASONING = "agent-reasoning"
    BACKEND_REPOSITORY = "backend-repository"
    PRODUCT_DATA = "product-data"
    UNKNOWN = "unknown"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class E2eCase(BaseModel):
    """Notion 시나리오 한 건의 고정 입력(번호는 원문 표 기준)."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(min_length=1)
    number: int
    query: str = Field(min_length=1)
    expected_concepts: list[str] = Field(default_factory=list)
    notes: str = ""


class E2eCaseRecord(BaseModel):
    """시나리오 실행 결과 - Notion 기록 템플릿과 1:1로 대응한다."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    number: int
    query: str
    nia_top_case: str
    selected_ingredients: list[str]
    ingredient_ids_resolved: list[str]
    ingredient_ambiguous: bool
    evidence_hit: bool
    citation_sources: list[str]
    product_hit: bool
    reason_evidence_aligned: str  # PASS/FAIL/N-A - 사람이 답변 텍스트를 읽고 판단
    sparse_evidence_handled: str  # PASS/FAIL/N-A
    unresolved_kinds: list[str]
    verdict: Verdict
    failure_classification: FailureClassification
    reason: str
    answer_excerpt: str
