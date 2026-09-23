"""Top-3 NIA Case 원문에서 런타임으로 추출하는 Claim 계약."""

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from agent.rag.case_schemas import CaseSearchHit
from agent.rag.schemas import EvidenceQueryAnchor, LookupStatus, RagModel

DEFAULT_CASE_CLAIM_LIMIT = 10
CASE_CLAIM_PROMPT_VERSION = "nia-case-ingredient-selection/v2"


class CaseClaimType(StrEnum):
    INGREDIENT_EFFECT = "ingredient_effect"
    COMBINATION_EFFECT = "combination_effect"


class ExtractedIngredientMention(RagModel):
    raw_name: str = Field(min_length=1)

    @field_validator("raw_name")
    @classmethod
    def normalize_raw_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("추출 성분명은 공백일 수 없습니다.")
        return normalized


class SelectedCaseIngredient(RagModel):
    """LLM이 Top-3 Case에서 고른 질문 관련 성분 후보."""

    case_id: str = Field(min_length=1)
    raw_name: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)

    @field_validator("raw_name", "source_quote")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Case 성분 후보 문자열은 공백일 수 없습니다.")
        return normalized


class ExtractedCaseClaim(RagModel):
    case_id: str = Field(min_length=1)
    claim_type: CaseClaimType
    ingredients: list[ExtractedIngredientMention] = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    combination_relation_quote: str | None = Field(default=None, min_length=1)

    @field_validator("source_quote")
    @classmethod
    def normalize_source_quote(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Case Claim 인용문은 공백일 수 없습니다.")
        return normalized

    @field_validator("combination_relation_quote")
    @classmethod
    def normalize_combination_relation_quote(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("조합 관계 인용문은 공백일 수 없습니다.")
        return normalized

    @model_validator(mode="after")
    def validate_claim_shape(self) -> Self:
        unique_names = list(dict.fromkeys(item.raw_name for item in self.ingredients))
        if len(unique_names) != len(self.ingredients):
            raise ValueError("한 Case Claim 안에 같은 성분명을 중복할 수 없습니다.")
        if self.claim_type is CaseClaimType.INGREDIENT_EFFECT and len(self.ingredients) != 1:
            raise ValueError("개별 성분 Claim에는 성분이 정확히 1개 필요합니다.")
        if self.claim_type is CaseClaimType.COMBINATION_EFFECT and len(self.ingredients) < 2:
            raise ValueError("조합 Claim에는 성분이 2개 이상 필요합니다.")
        return self


class CaseIngredientSelectionModelOutput(RagModel):
    """LLM은 효능 문장이나 ID를 만들지 않고 질문 관련 성분명만 고른다."""

    ingredients: list[SelectedCaseIngredient] = Field(default_factory=list)


class CaseClaimExtractionRequest(RagModel):
    query: str = Field(min_length=1)
    cases: list[CaseSearchHit] = Field(min_length=1, max_length=3)
    limit: int = Field(default=DEFAULT_CASE_CLAIM_LIMIT, ge=1)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Claim 추출 입력 Case ID가 중복되었습니다.")
        return self


class CaseClaimPromptCase(RagModel):
    """외부·로컬 채팅 모델에 전달할 최소 Case 필드."""

    case_id: str = Field(min_length=1)
    page_content: str = Field(min_length=1)


class CaseClaimPromptInput(RagModel):
    """성별·연령·원본 파일 provenance를 제외한 Claim 추출 입력."""

    query: str = Field(min_length=1)
    cases: list[CaseClaimPromptCase] = Field(min_length=1, max_length=3)
    limit: int = Field(ge=1)


class CaseClaimExtractionResult(RagModel):
    status: LookupStatus
    claims: list[ExtractedCaseClaim] = Field(default_factory=list)
    model: str | None = Field(default=None, min_length=1)
    prompt_version: str = Field(default=CASE_CLAIM_PROMPT_VERSION, min_length=1)
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        if self.status is LookupStatus.SUCCESS:
            if not self.claims:
                raise ValueError("SUCCESS Claim 추출 결과에는 Claim이 필요합니다.")
            if self.model is None:
                raise ValueError("SUCCESS Claim 추출 결과에는 모델명이 필요합니다.")
            return self
        if self.claims:
            raise ValueError("성공하지 않은 Claim 추출 결과에는 Claim을 넣을 수 없습니다.")
        if self.status is LookupStatus.ERROR and not self.error_message:
            raise ValueError("ERROR Claim 추출 결과에는 원인 메시지가 필요합니다.")
        return self


class CaseClaimValidationReason(StrEnum):
    UNKNOWN_CASE_ID = "unknown_case_id"
    QUOTE_NOT_FOUND = "quote_not_found"
    INGREDIENT_NOT_IN_QUOTE = "ingredient_not_in_quote"
    INGREDIENT_NAME_ONLY_QUOTE = "ingredient_name_only_quote"
    COMBINATION_RELATION_NOT_FOUND = "combination_relation_not_found"
    COMBINATION_RELATION_NOT_EXPLICIT = "combination_relation_not_explicit"
    DUPLICATE_CLAIM = "duplicate_claim"


class RejectedCaseClaim(RagModel):
    claim: ExtractedCaseClaim
    reason: CaseClaimValidationReason
    message: str = Field(min_length=1)


class CaseClaimValidationRequest(RagModel):
    cases: list[CaseSearchHit] = Field(min_length=1, max_length=3)
    claims: list[ExtractedCaseClaim] = Field(default_factory=list)


class CaseClaimValidationResult(RagModel):
    valid_claims: list[ExtractedCaseClaim] = Field(default_factory=list)
    rejected_claims: list[RejectedCaseClaim] = Field(default_factory=list)


class CaseClaimIngredientResolutionStatus(StrEnum):
    MATCHED = "matched"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


class ResolvedCaseClaimIngredient(RagModel):
    raw_name: str = Field(min_length=1)
    ingredient_id: str | None = Field(default=None, min_length=1)
    canonical_name: str | None = Field(default=None, min_length=1)
    status: CaseClaimIngredientResolutionStatus

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if (
            self.status is CaseClaimIngredientResolutionStatus.MATCHED
            and self.ingredient_id is None
        ):
            raise ValueError("MATCHED Case Claim 성분에는 ingredient_id가 필요합니다.")
        if (
            self.status is not CaseClaimIngredientResolutionStatus.MATCHED
            and (self.ingredient_id is not None or self.canonical_name is not None)
        ):
            raise ValueError("미확정 Case Claim 성분에는 표준 성분 정보를 넣을 수 없습니다.")
        return self


class ResolvedCaseClaim(RagModel):
    statement_id: str = Field(min_length=1)
    claim: ExtractedCaseClaim
    ingredients: list[ResolvedCaseClaimIngredient] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ingredient_count(self) -> Self:
        if len(self.ingredients) != len(self.claim.ingredients):
            raise ValueError("Case Claim의 추출 성분과 식별 결과 수가 일치해야 합니다.")
        return self

    def matched_ingredient_ids(self) -> list[str]:
        return [
            ingredient.ingredient_id
            for ingredient in self.ingredients
            if ingredient.status is CaseClaimIngredientResolutionStatus.MATCHED
            and ingredient.ingredient_id is not None
        ]

    def is_fully_resolved(self) -> bool:
        return len(self.matched_ingredient_ids()) == len(self.ingredients)


class CaseClaimBundle(RagModel):
    extraction: CaseClaimExtractionResult
    validation: CaseClaimValidationResult | None = None
    resolved_claims: list[ResolvedCaseClaim] = Field(default_factory=list)
    evidence_anchors: list[EvidenceQueryAnchor] = Field(default_factory=list)
