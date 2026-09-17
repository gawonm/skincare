"""NIA Claim 검색 경계에서 사용하는 구조화 타입.

Claim은 탐색용 주장이고 Evidence는 검증 근거이므로 두 타입을 상속하거나 합치지 않는다.
원문 statement의 타입별 필드를 보존해 단일 ``claim: str`` 변환에서 생기는 정보 손실을 막는다.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from agent.rag.schemas import (
    DEFAULT_SEARCH_LIMIT,
    EvidenceConditions,
    EvidenceRecord,
    LookupStatus,
    RagModel,
)


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


class ClaimVerificationStatus(StrEnum):
    SUPPORTED = "supported"
    INSUFFICIENT = "insufficient"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class RecommendationBasis(StrEnum):
    EVIDENCE_SUPPORTED = "evidence_supported"
    CLAIM_ONLY = "claim_only"


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

    def verification_query(self) -> str:
        names = list(
            dict.fromkeys(
                anchor.raw_name_ko or anchor.raw_name for anchor in self.ingredient_anchors()
            )
        )
        statement = self.display_text()
        if not names:
            return statement
        # 표시 문구와 달리 Evidence 검색에는 성분명을 명시해 다른 성분의 효능 문서가 섞이지 않게 한다.
        return f"{' + '.join(names)}: {statement}"


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


class ClaimResolvedTarget(RagModel):
    statement_id: str = Field(min_length=1)
    ingredient_ids: list[str] = Field(min_length=1)
    query: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ingredients(self) -> Self:
        if len(self.ingredient_ids) != len(set(self.ingredient_ids)):
            raise ValueError("Claim 검증 대상의 ingredient_id가 중복되었습니다.")
        return self


class ClaimVerificationRequest(RagModel):
    target: ClaimResolvedTarget
    known_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)


class ClaimVerificationResult(RagModel):
    statement_id: str = Field(min_length=1)
    ingredient_ids: list[str] = Field(min_length=1)
    status: ClaimVerificationStatus
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    summary: str | None = Field(default=None, min_length=1)
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_payload(self) -> Self:
        if len(self.ingredient_ids) != len(set(self.ingredient_ids)):
            raise ValueError("Claim 검증 결과의 ingredient_id가 중복되었습니다.")
        record_ids = [record.evidence_id for record in self.evidence_records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Claim 검증 결과의 evidence_id가 중복되었습니다.")
        if self.evidence_ids != record_ids:
            raise ValueError("Claim 검증 결과의 evidence_ids와 EvidenceRecord가 일치하지 않습니다.")
        if self.status is ClaimVerificationStatus.SUPPORTED:
            if not self.evidence_ids or self.summary is None:
                raise ValueError("SUPPORTED Claim 검증 결과에는 근거와 요약이 필요합니다.")
        elif self.evidence_ids or self.evidence_records:
            # 검증에 쓰지 못한 검색 자료가 Citation으로 승격되지 않도록 결과에서 분리한다.
            raise ValueError("SUPPORTED가 아닌 Claim 결과에는 인용 가능한 근거를 넣을 수 없습니다.")
        return self


class ClaimVerificationBundle(RagModel):
    results: list[ClaimVerificationResult] = Field(default_factory=list)


class IngredientRecommendationCandidate(RagModel):
    ingredient_id: str = Field(min_length=1)
    basis: RecommendationBasis
    statement_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    limitation: str | None = Field(default=None, min_length=1)


class IngredientRecommendationSet(RagModel):
    candidates: list[IngredientRecommendationCandidate] = Field(default_factory=list)


class ClaimBundle(RagModel):
    search: ClaimSearchResult
    target_ids: list[str] = Field(default_factory=list)
    resolved_targets: list[ClaimResolvedTarget] = Field(default_factory=list)
    unresolved_anchors: list[UnresolvedClaimAnchor] = Field(default_factory=list)
