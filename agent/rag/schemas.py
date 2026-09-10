"""RAG와 루틴 도구가 주고받는 구조화 타입."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, SecretStr

DEFAULT_SEARCH_LIMIT = 5
DEFAULT_ROUTINE_FREQUENCY = 2


class RagModel(BaseModel):
    """RAG 경계에서 알 수 없는 필드가 조용히 유실되지 않게 하는 기본 모델."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LookupStatus(StrEnum):
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class ProductCategory(StrEnum):
    CLEANSER = "cleanser"
    TONER = "toner"
    SERUM = "serum"
    MOISTURIZER = "moisturizer"
    SUNSCREEN = "sunscreen"


class ProductTexture(StrEnum):
    LIGHT = "light"
    RICH = "rich"
    GEL = "gel"
    CREAM = "cream"


class EvidenceReviewStatus(StrEnum):
    VERIFIED = "verified"
    UNREVIEWED = "unreviewed"
    DEMO = "demo"


class RegulatoryConfidence(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class RegulateType(StrEnum):
    PROHIBITED = "prohibited"
    LIMITED = "limited"


class EvidenceSourceType(StrEnum):
    UNKNOWN = "unknown"
    DEMO = "demo"
    INGREDIENT_KNOWLEDGE = "ingredient_knowledge"
    MFDS = "mfds_restricted_ingredient"
    CIR = "cir"
    PAPER = "paper"
    HETIONET = "hetionet"


class EvidenceTextKind(StrEnum):
    EXCERPT = "excerpt"
    SUMMARY = "summary"


class EvidenceScope(StrEnum):
    INGREDIENT = "ingredient"
    PRODUCT = "product"
    PAIR = "pair"
    ASSOCIATION = "association"


class ApplicabilityStatus(StrEnum):
    APPLICABLE = "applicable"
    LIMITED = "limited"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class DayPeriod(StrEnum):
    MORNING = "morning"
    EVENING = "evening"


class Weekday(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class ConstraintSource(StrEnum):
    PRODUCT_DIRECTIONS = "product_directions"
    USER = "user"
    SERVICE_POLICY = "service_policy"


class IngredientResolveRequest(RagModel):
    name: str = Field(min_length=1)
    language: str = Field(default="ko", min_length=2)


class IngredientRecord(RagModel):
    ingredient_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    ingredient_code: int | None = None
    source_version: str | None = None
    aliases: list[str] = Field(default_factory=list)
    is_demo: bool = True


class IngredientResolveResult(RagModel):
    status: LookupStatus
    ingredient: IngredientRecord | None = None
    ambiguous_candidates: list[IngredientRecord] = Field(default_factory=list)
    error_message: str | None = None


class ProductRecord(RagModel):
    product_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: ProductCategory
    texture: ProductTexture
    ingredient_ids: list[str] = Field(default_factory=list)
    directions: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    checked_at: str = Field(min_length=1)
    is_demo: bool = True


class ProductSearchFilters(RagModel):
    category: ProductCategory | None = None
    texture: ProductTexture | None = None
    ingredient_ids: list[str] = Field(default_factory=list)


class ProductSearchRequest(RagModel):
    allow_discovery: bool = True
    query: str = ""
    filters: ProductSearchFilters = Field(default_factory=ProductSearchFilters)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)


class ProductSearchResult(RagModel):
    status: LookupStatus
    products: list[ProductRecord] = Field(default_factory=list)
    unsupported_conditions: list[str] = Field(default_factory=list)
    error_message: str | None = None


class ProductGetRequest(RagModel):
    product_id: str = Field(min_length=1)
    version: str | None = None


class ProductGetResult(RagModel):
    status: LookupStatus
    product: ProductRecord | None = None
    error_message: str | None = None


class EvidenceConditions(RagModel):
    concentration: str | None = None
    formulation: str | None = None
    route: str | None = None
    usage: str | None = None
    duration: str | None = None
    ph: str | None = None
    jurisdiction: str | None = None


class EvidenceRecord(RagModel):
    source_type: EvidenceSourceType = EvidenceSourceType.UNKNOWN
    text_kind: EvidenceTextKind = EvidenceTextKind.SUMMARY
    scope: EvidenceScope = EvidenceScope.INGREDIENT
    topic: str | None = None
    jurisdiction: str | None = None
    raw_conditions: str | None = None
    source_reference: str | None = None
    regulatory_confidence: RegulatoryConfidence | None = None
    regulate_type: RegulateType | None = None
    published_at: str | None = None
    collected_at: str | None = None
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    document_version: str | None = Field(default=None, min_length=1)
    text: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)
    review_status: EvidenceReviewStatus
    url: str | None = None
    is_demo: bool = True


class EvidenceSearchRequest(RagModel):
    known_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)
    query: str = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)
    # 제품과 전성분을 한 집합으로 합치면 병용 대상 두 개를 복원할 수 없다.
    combination_target_ids: list[str] = Field(default_factory=list)


class QuestionIntent(StrEnum):
    EFFICACY = "efficacy"
    SKIN_TYPE = "skin_type"
    CONCENTRATION = "concentration"
    PRECAUTION = "precaution"
    REGULATION = "regulation"
    USAGE_FREQUENCY = "usage_frequency"
    COMBINATION = "combination"


class RagConfidenceTier(StrEnum):
    UNKNOWN = "unknown"
    OFFICIAL_REGULATORY = "official_regulatory"
    STRUCTURED_KNOWLEDGE = "structured_knowledge"
    AI_GENERATED_REVIEWED = "ai_generated_reviewed"


class UnverifiableReason(StrEnum):
    NO_EVIDENCE_FOUND = "no_evidence_found"
    UNREVIEWED_EVIDENCE = "unreviewed_evidence"
    NOT_RELEVANT_TO_QUESTION = "not_relevant_to_question"
    MISSING_COMBINATION_EVIDENCE = "missing_combination_evidence"
    CITATION_VALIDATION_FAILED = "citation_validation_failed"


class RagDocumentField(RagModel):
    field_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    intents: list[QuestionIntent] = Field(default_factory=list)


class RagDocument(RagModel):
    # 영속 테이블을 가정하지 않고 기존 조회 DTO의 출처·원문 조건을 함께 운반한다.
    evidence: EvidenceRecord
    fields: list[RagDocumentField] = Field(min_length=1)
    confidence_tier: RagConfidenceTier = RagConfidenceTier.UNKNOWN


class RagChunkDraft(RagModel):
    chunk_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    evidence: EvidenceRecord
    intents: list[QuestionIntent] = Field(default_factory=list)
    confidence_tier: RagConfidenceTier = RagConfidenceTier.UNKNOWN


class EmbeddingVector(RagModel):
    values: list[FiniteFloat] = Field(min_length=1)


class EmbeddingRequest(RagModel):
    texts: list[str] = Field(min_length=1)


class EmbeddingResult(RagModel):
    vectors: list[EmbeddingVector]
    model: str = Field(min_length=1)


class EmbeddedChunk(RagModel):
    draft: RagChunkDraft
    vector: EmbeddingVector
    embedding_model: str = Field(min_length=1)


class RetrievedChunk(RagModel):
    chunk: RagChunkDraft
    vector_similarity: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    bm25_relevance: float | None = Field(default=None, allow_inf_nan=False)
    fused_score: float = Field(default=0, ge=0, allow_inf_nan=False)


class HybridSearchRequest(RagModel):
    request: EvidenceSearchRequest
    vector: EmbeddingVector
    embedding_model: str


class HybridSearchResult(RagModel):
    status: LookupStatus
    vector_results: list[RetrievedChunk] = Field(default_factory=list)
    bm25_results: list[RetrievedChunk] = Field(default_factory=list)
    error_message: str | None = None


class HybridFusionRequest(RagModel):
    results: HybridSearchResult
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)


class RagRetrievalPolicy(RagModel):
    # 새 브랜치의 특정 데이터셋에서 고른 임계값을 미확정 검색기에 강제하지 않는다.
    free_text_min_vector_similarity: float = Field(ge=-1, le=1)
    rrf_k: int = Field(default=60, gt=0)


class OpenAiModelConfig(RagModel):
    api_key: SecretStr
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(default=30, gt=0)
    max_retries: int = Field(default=1, ge=0)


class GeneratedClaim(RagModel):
    sentence: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class GeneratedClaims(RagModel):
    claims: list[GeneratedClaim] = Field(default_factory=list)


class ClaimGenerationRequest(RagModel):
    question: str = Field(min_length=1)
    records: list[EvidenceRecord] = Field(min_length=1)
    known_conditions: EvidenceConditions
    is_combination: bool = False


class AnsweredClaim(RagModel):
    sentence: str = Field(min_length=1)
    sources: list[EvidenceRecord] = Field(min_length=1)


class IngredientVerificationResult(RagModel):
    claims: list[AnsweredClaim] = Field(default_factory=list)
    unverifiable_reason: UnverifiableReason | None = None

    @property
    def has_verifiable_evidence(self) -> bool:
        return bool(self.claims) and self.unverifiable_reason is None

    @property
    def answer(self) -> str:
        return " ".join(claim.sentence for claim in self.claims)


class PerTargetResult(RagModel):
    target_id: str
    result: IngredientVerificationResult


class RagQueryResult(RagModel):
    per_target: list[PerTargetResult] = Field(default_factory=list)
    combination: IngredientVerificationResult | None = None
    free_text: IngredientVerificationResult | None = None


class EvidenceSearchResult(RagModel):
    status: LookupStatus
    records: list[EvidenceRecord] = Field(default_factory=list)
    error_message: str | None = None
    chunks: list[RetrievedChunk] = Field(default_factory=list)


class ApplicabilityRequest(RagModel):
    evidence: EvidenceRecord
    known_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)


class ApplicabilityAssessment(RagModel):
    evidence_id: str = Field(min_length=1)
    status: ApplicabilityStatus
    reasons: list[str] = Field(default_factory=list)


class EvidenceBundle(RagModel):
    search: EvidenceSearchResult
    assessments: list[ApplicabilityAssessment] = Field(default_factory=list)
    generated: RagQueryResult | None = None


class ProductCandidate(RagModel):
    rank: int = Field(ge=1)
    product: ProductRecord
    reasons: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ProductCandidateSet(RagModel):
    candidate_set_id: str = Field(min_length=1)
    candidates: list[ProductCandidate] = Field(default_factory=list)
    is_demo: bool = True


class RoutineConstraint(RagModel):
    description: str = Field(min_length=1)
    source: ConstraintSource
    source_id: str | None = None


class RoutinePlacement(RagModel):
    weekday: Weekday
    period: DayPeriod
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    order: int = Field(ge=1)
    reason: str = Field(min_length=1)


class RoutinePlan(RagModel):
    routine_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    placements: list[RoutinePlacement] = Field(default_factory=list)
    constraints: list[RoutineConstraint] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    is_demo: bool = True


class RoutinePlanRequest(RagModel):
    chat_room_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    products: list[ProductRecord] = Field(min_length=1)
    excluded_weekdays: list[Weekday] = Field(default_factory=list)
    frequency_per_week: int = Field(default=DEFAULT_ROUTINE_FREQUENCY, ge=1, le=7)
    current_plan: RoutinePlan | None = None


class RoutineValidationRequest(RagModel):
    plan: RoutinePlan
    excluded_weekdays: list[Weekday] = Field(default_factory=list)


class RoutineValidationResult(RagModel):
    valid: bool
    violations: list[str] = Field(default_factory=list)
