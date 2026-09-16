"""NIA Claim 검색 경계에서 사용하는 구조화 타입.

Claim은 탐색용 주장이고 Evidence는 검증 근거이므로 두 타입을 상속하거나 합치지 않는다.
원문 statement의 타입별 필드를 보존해 단일 ``claim: str`` 변환에서 생기는 정보 손실을 막는다.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from agent.rag.schemas import DEFAULT_SEARCH_LIMIT, LookupStatus, RagModel


class ClaimStatementType(StrEnum):
    CASE_OBSERVATION = "case_observation"
    CAUSE_CLAIM = "cause_claim"
    INGREDIENT_EFFECT_CLAIM = "ingredient_effect_claim"
    PRECAUTION = "precaution"
    USAGE_INSTRUCTION = "usage_instruction"
    COMBINATION_CLAIM = "combination_claim"
    CONTEXTUAL_FACTOR = "contextual_factor"


class ClaimMatchingStatus(StrEnum):
    UNRESOLVED = "unresolved"
    UNRESOLVED_AMBIGUOUS_FAMILY = "unresolved_ambiguous_family"
    MATCHED = "matched"
    REJECTED = "rejected"


class ClaimSupportStatus(StrEnum):
    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class ClaimAnnotationStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ClaimConfidence(StrEnum):
    HIGH = "high"
    LOW = "low"


class ClaimTimeOfDay(StrEnum):
    MORNING = "morning"
    EVENING = "evening"
    DAYTIME = "daytime"
    NIGHT = "night"


class ClaimFrequencyPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    EVERY_OTHER_DAY = "every_other_day"


class ClaimSourceSpan(RagModel):
    json_path: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Claim 원문 범위의 end는 start보다 커야 합니다.")
        return self


class ClaimCaseContext(RagModel):
    age_raw: int | None = None
    age_text_raw: str | None = None
    gender_raw: str | None = None
    skin_type_raw: str | None = None
    skin_concerns_raw: list[str] = Field(default_factory=list)
    initial_skin_condition_raw: str | None = None


class ClaimIngredientAnchor(RagModel):
    raw_name: str = Field(min_length=1)
    raw_name_ko: str | None = Field(default=None, min_length=1)
    ingredient_id: str | None = Field(default=None, min_length=1)
    matching_status: ClaimMatchingStatus

    @model_validator(mode="after")
    def validate_matching_result(self) -> Self:
        if self.matching_status is ClaimMatchingStatus.MATCHED and self.ingredient_id is None:
            raise ValueError("MATCHED Claim 성분에는 ingredient_id가 필요합니다.")
        if self.matching_status is not ClaimMatchingStatus.MATCHED and self.ingredient_id is not None:
            raise ValueError("미확정 Claim 성분에는 ingredient_id를 넣을 수 없습니다.")
        return self


class ClaimFrequency(RagModel):
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)
    period: ClaimFrequencyPeriod

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.maximum < self.minimum:
            raise ValueError("Claim 사용 빈도의 maximum은 minimum보다 작을 수 없습니다.")
        return self


class CaseObservationContent(RagModel):
    statement_type: Literal[ClaimStatementType.CASE_OBSERVATION] = (
        ClaimStatementType.CASE_OBSERVATION
    )
    subject: str = Field(min_length=1)


class CauseClaimContent(RagModel):
    statement_type: Literal[ClaimStatementType.CAUSE_CLAIM] = ClaimStatementType.CAUSE_CLAIM
    subject: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    objects: list[str] = Field(min_length=1)
    scope_text: str | None = None


class IngredientEffectClaimContent(RagModel):
    statement_type: Literal[ClaimStatementType.INGREDIENT_EFFECT_CLAIM] = (
        ClaimStatementType.INGREDIENT_EFFECT_CLAIM
    )
    subject: ClaimIngredientAnchor
    object: str = Field(min_length=1)
    concentration_raw: str | None = None


class PrecautionContent(RagModel):
    statement_type: Literal[ClaimStatementType.PRECAUTION] = ClaimStatementType.PRECAUTION
    subject: str = Field(min_length=1)
    relation: str = Field(min_length=1)


class UsageInstructionContent(RagModel):
    statement_type: Literal[ClaimStatementType.USAGE_INSTRUCTION] = (
        ClaimStatementType.USAGE_INSTRUCTION
    )
    action_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    time_of_day: list[ClaimTimeOfDay] = Field(default_factory=list)
    frequency: ClaimFrequency | None = None
    ingredient_ids: list[str] = Field(default_factory=list)


class CombinationClaimContent(RagModel):
    statement_type: Literal[ClaimStatementType.COMBINATION_CLAIM] = (
        ClaimStatementType.COMBINATION_CLAIM
    )
    subjects: list[ClaimIngredientAnchor] = Field(min_length=2)
    subject_plural_mode: str = Field(min_length=1)
    object: str = Field(min_length=1)


class ContextualFactorContent(RagModel):
    statement_type: Literal[ClaimStatementType.CONTEXTUAL_FACTOR] = (
        ClaimStatementType.CONTEXTUAL_FACTOR
    )
    factor_raw: str = Field(min_length=1)
    details_raw: str = Field(min_length=1)
    priority_raw: int
    causal_link_status: str = Field(min_length=1)


ClaimContent = Annotated[
    CaseObservationContent
    | CauseClaimContent
    | IngredientEffectClaimContent
    | PrecautionContent
    | UsageInstructionContent
    | CombinationClaimContent
    | ContextualFactorContent,
    Field(discriminator="statement_type"),
]


class ClaimHit(RagModel):
    statement_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    content: ClaimContent
    source_spans: list[ClaimSourceSpan] = Field(min_length=1)
    case_context: ClaimCaseContext
    support_status: ClaimSupportStatus = ClaimSupportStatus.UNVERIFIED
    annotation_status: ClaimAnnotationStatus
    confidence: ClaimConfidence
    retrieval_score: FiniteFloat

    def ingredient_anchors(self) -> list[ClaimIngredientAnchor]:
        if isinstance(self.content, IngredientEffectClaimContent):
            return [self.content.subject]
        if isinstance(self.content, CombinationClaimContent):
            return list(self.content.subjects)
        return []

    def matched_ingredient_ids(self) -> list[str]:
        if isinstance(self.content, UsageInstructionContent):
            return list(self.content.ingredient_ids)
        return [
            anchor.ingredient_id
            for anchor in self.ingredient_anchors()
            if anchor.matching_status is ClaimMatchingStatus.MATCHED
            and anchor.ingredient_id is not None
        ]

    def display_text(self) -> str:
        if isinstance(self.content, IngredientEffectClaimContent):
            return self.content.object
        if isinstance(self.content, CombinationClaimContent):
            return self.content.object
        if isinstance(self.content, (CaseObservationContent, PrecautionContent)):
            return self.content.subject
        if isinstance(self.content, UsageInstructionContent):
            return self.content.action
        if isinstance(self.content, CauseClaimContent):
            return f"{self.content.subject}: {', '.join(self.content.objects)}"
        return self.content.details_raw


class ClaimSearchRequest(RagModel):
    query: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)


class ClaimSearchResult(RagModel):
    status: LookupStatus
    hits: list[ClaimHit] = Field(default_factory=list)
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        if self.status is LookupStatus.SUCCESS and not self.hits:
            raise ValueError("SUCCESS Claim 검색 결과에는 hit이 필요합니다.")
        if self.status is not LookupStatus.SUCCESS and self.hits:
            raise ValueError("성공하지 않은 Claim 검색 결과에는 hit을 넣을 수 없습니다.")
        if self.status is LookupStatus.ERROR and not self.error_message:
            raise ValueError("ERROR Claim 검색 결과에는 원인 메시지가 필요합니다.")
        return self


class UnresolvedClaimAnchor(RagModel):
    statement_id: str = Field(min_length=1)
    raw_name: str = Field(min_length=1)


class ClaimBundle(RagModel):
    search: ClaimSearchResult
    target_ids: list[str] = Field(default_factory=list)
    unresolved_anchors: list[UnresolvedClaimAnchor] = Field(default_factory=list)
