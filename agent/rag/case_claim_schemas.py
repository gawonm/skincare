"""Top-3 NIA Case 원문에서 런타임으로 추출하는 Claim 계약."""

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from agent.rag.case_schemas import CaseSearchHit
from agent.rag.schemas import LookupStatus, RagModel

DEFAULT_CASE_CLAIM_LIMIT = 10
CASE_CLAIM_PROMPT_VERSION = "nia-case-claim/v1"


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


class ExtractedCaseClaim(RagModel):
    case_id: str = Field(min_length=1)
    claim_type: CaseClaimType
    ingredients: list[ExtractedIngredientMention] = Field(min_length=1)
    source_quote: str = Field(min_length=1)

    @field_validator("source_quote")
    @classmethod
    def normalize_source_quote(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Case Claim 인용문은 공백일 수 없습니다.")
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


class CaseClaimBundle(RagModel):
    extraction: CaseClaimExtractionResult
