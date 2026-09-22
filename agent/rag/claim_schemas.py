"""NIA Claim 검색 경계에서 사용하는 최소 구조화 타입.

Claim은 탐색용 주장이고 Evidence는 검증 근거이므로 두 타입을 상속하거나 합치지 않는다.
원문 전체 구조 대신 검색·검증에 필요한 provenance와 성분 연결만 전달한다.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, FiniteFloat, model_validator

from agent.rag.schemas import (
    DEFAULT_SEARCH_LIMIT,
    EmbeddingVector,
    EvidenceConditions,
    EvidenceQueryAnchor,
    EvidenceQueryOrigin,
    EvidenceRecord,
    LookupStatus,
    ProductRecord,
    RagModel,
)

DEVELOPMENT_CLAIM_ANNOTATION_VERSION = "fixture-claim-v1"


class ClaimStatementType(StrEnum):
    CASE_OBSERVATION = "case_observation"
    CAUSE_CLAIM = "cause_claim"
    INGREDIENT_EFFECT_CLAIM = "ingredient_effect_claim"
    PRECAUTION = "precaution"
    USAGE_INSTRUCTION = "usage_instruction"
    COMBINATION_CLAIM = "combination_claim"
    CONTEXTUAL_FACTOR = "contextual_factor"


class ClaimIngredientMatchingStatus(StrEnum):
    UNRESOLVED = "unresolved"
    UNRESOLVED_AMBIGUOUS_FAMILY = "unresolved_ambiguous_family"
    MATCHED = "matched"
    REJECTED = "rejected"


class ClaimIngestionDecision(StrEnum):
    BLOCKED = "blocked"
    HUMAN_REVIEW = "human_review"
    INGESTIBLE_STRUCTURED = "ingestible_structured"
    INGESTIBLE_FREE_TEXT = "ingestible_free_text"


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


class ClaimIngredientRef(RagModel):
    raw_name: str | None = Field(default=None, min_length=1)
    ingredient_id: str | None = Field(default=None, min_length=1)
    matching_status: ClaimIngredientMatchingStatus

    @model_validator(mode="after")
    def validate_matching_result(self) -> Self:
        if (
            self.matching_status is ClaimIngredientMatchingStatus.MATCHED
            and self.ingredient_id is None
        ):
            raise ValueError("MATCHED Claim 성분에는 ingredient_id가 필요합니다.")
        if (
            self.matching_status is not ClaimIngredientMatchingStatus.MATCHED
            and self.ingredient_id is not None
        ):
            raise ValueError("미확정 Claim 성분에는 ingredient_id를 넣을 수 없습니다.")
        return self


class ClaimHit(RagModel):
    claim_chunk_id: str = Field(min_length=1)
    statement_id: str = Field(min_length=1)
    statement_type: ClaimStatementType
    content: str = Field(min_length=1)
    score: FiniteFloat
    ingredient_refs: list[ClaimIngredientRef] = Field(default_factory=list)
    source_record_id: str = Field(min_length=1)
    annotation_version: str = Field(min_length=1)
    decision: ClaimIngestionDecision
    support_status: ClaimSupportStatus = ClaimSupportStatus.UNVERIFIED

    def ingredient_anchors(self) -> list[ClaimIngredientRef]:
        return list(self.ingredient_refs)

    def matched_ingredient_ids(self) -> list[str]:
        return [
            anchor.ingredient_id
            for anchor in self.ingredient_refs
            if anchor.matching_status is ClaimIngredientMatchingStatus.MATCHED
            and anchor.ingredient_id is not None
        ]

    def display_text(self) -> str:
        return self.content

    def verification_query(self) -> str:
        names = list(
            dict.fromkeys(
                anchor.raw_name
                for anchor in self.ingredient_refs
                if anchor.raw_name is not None
            )
        )
        if not names:
            return self.content
        # 표시 문구와 달리 Evidence 검색에는 성분명을 명시해 다른 성분의 효능 문서가 섞이지 않게 한다.
        return f"{' + '.join(names)}: {self.content}"


class ClaimSearchRequest(RagModel):
    query: str = Field(min_length=1)
    query_embedding: EmbeddingVector | None = None
    annotation_version: str = Field(min_length=1)
    top_k: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)
    ingredient_ids: list[str] = Field(default_factory=list)
    skin_concerns: list[str] = Field(default_factory=list)


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


class ClaimVerificationRequest(RagModel):
    anchor: EvidenceQueryAnchor
    known_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)

    @model_validator(mode="after")
    def validate_claim_anchor(self) -> Self:
        if self.anchor.origin not in (
            EvidenceQueryOrigin.CLAIM_HIT,
            EvidenceQueryOrigin.CASE_CLAIM,
        ):
            raise ValueError("Claim 검증에는 Claim 유래 Evidence anchor가 필요합니다.")
        return self


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


class RecommendationProductMatch(RagModel):
    product: ProductRecord
    evidence_supported_ingredient_ids: list[str] = Field(default_factory=list)
    claim_only_ingredient_ids: list[str] = Field(default_factory=list)
    statement_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    def basis(self) -> RecommendationBasis:
        if self.evidence_supported_ingredient_ids:
            return RecommendationBasis.EVIDENCE_SUPPORTED
        return RecommendationBasis.CLAIM_ONLY


class ClaimBundle(RagModel):
    search: ClaimSearchResult
    target_ids: list[str] = Field(default_factory=list)
    evidence_anchors: list[EvidenceQueryAnchor] = Field(default_factory=list)
    unresolved_anchors: list[UnresolvedClaimAnchor] = Field(default_factory=list)
