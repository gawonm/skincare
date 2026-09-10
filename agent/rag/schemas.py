"""RAG와 루틴 도구가 주고받는 구조화 타입."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

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


class EvidenceSearchResult(RagModel):
    status: LookupStatus
    records: list[EvidenceRecord] = Field(default_factory=list)
    error_message: str | None = None


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
