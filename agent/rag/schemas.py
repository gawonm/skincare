"""RAG와 루틴 도구가 주고받는 구조화 타입."""

from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    SecretStr,
    field_validator,
    model_validator,
)

DEFAULT_SEARCH_LIMIT = 5
DEFAULT_ROUTINE_FREQUENCY = 2
MAX_ROUTINE_RULES = 32
MAX_ROUTINE_PLACEMENTS = 64
DEFAULT_EMBEDDING_BATCH_SIZE = 16
DEFAULT_OPENAI_EMBEDDING_BATCH_SIZE = 100
DEFAULT_OPENAI_EMBEDDING_DIMENSIONS = 1536
BGE_M3_EMBEDDING_DIMENSIONS = 1024
DEFAULT_RERANKER_BATCH_SIZE = 8
DEFAULT_RERANKER_MAX_LENGTH = 512
DEFAULT_RERANK_CANDIDATE_LIMIT = 30


class RagModel(BaseModel):
    """RAG 경계에서 알 수 없는 필드가 조용히 유실되지 않게 하는 기본 모델."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LookupStatus(StrEnum):
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class EvidenceQueryOrigin(StrEnum):
    CLAIM_HIT = "claim_hit"
    CASE_CLAIM = "case_claim"
    DIRECT_QUERY = "direct_query"


class IngredientScope(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


class IngredientMatchMode(StrEnum):
    ANY = "any"
    ALL = "all"


class EvidenceClaimTopic(StrEnum):
    EFFICACY = "efficacy"
    PRECAUTION = "precaution"
    CONCENTRATION_REGULATION = "concentration_regulation"
    USAGE_INSTRUCTION = "usage_instruction"
    COMBINATION = "combination"


class EvidenceQueryAnchor(RagModel):
    """Claim 또는 직접 질의를 Evidence 검색 조건으로 고정한 비영속 계약."""

    anchor_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    origin: EvidenceQueryOrigin
    origin_ref: str | None = Field(default=None, min_length=1)
    ingredient_scope: IngredientScope
    ingredient_refs: list[str] = Field(min_length=1)
    ingredient_match_mode: IngredientMatchMode | None = None
    claim_topic: EvidenceClaimTopic
    query_text: str = Field(min_length=1)
    query_terms: list[str] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)

    @field_validator("query_text")
    @classmethod
    def validate_query_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Evidence 질의문은 공백일 수 없습니다.")
        return normalized

    @field_validator("query_terms")
    @classmethod
    def normalize_query_terms(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("ingredient_refs")
    @classmethod
    def validate_ingredient_refs(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Evidence 성분 참조는 공백일 수 없습니다.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Evidence 성분 참조가 중복되었습니다.")
        return normalized

    @model_validator(mode="after")
    def validate_origin_and_scope(self) -> Self:
        if self.origin in (
            EvidenceQueryOrigin.CLAIM_HIT,
            EvidenceQueryOrigin.CASE_CLAIM,
        ) and self.origin_ref is None:
            raise ValueError("Claim 유래 Evidence 질의에는 origin_ref가 필수입니다.")
        if self.origin is EvidenceQueryOrigin.DIRECT_QUERY and self.origin_ref is not None:
            raise ValueError("직접 Evidence 질의의 origin_ref는 반드시 None이어야 합니다.")
        if self.ingredient_scope is IngredientScope.SINGLE:
            if len(self.ingredient_refs) != 1:
                raise ValueError("단일 성분 범위에는 성분 참조가 정확히 1개 필요합니다.")
            if self.ingredient_match_mode is not None:
                raise ValueError("단일 성분 범위의 match mode는 반드시 None이어야 합니다.")
            return self
        if len(self.ingredient_refs) < 2:
            raise ValueError("다중 성분 범위에는 성분 참조가 2개 이상 필요합니다.")
        if self.ingredient_match_mode is None:
            raise ValueError("다중 성분 범위에는 ingredient_match_mode가 필수입니다.")
        return self


class ProductClassification(RagModel):
    """분류 코드는 데이터 제공자가 소유하며 표시 이름 변경과 독립적으로 유지한다."""

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)


class ProductCategory(ProductClassification):
    """조회 어댑터가 지원하는 상품 카테고리."""


class ProductTexture(ProductClassification):
    """젤·크림 등 데이터에서 확인된 제형. 사용감과 별개다."""


class ProductSkinFeel(ProductClassification):
    """가벼움·리치함 등 데이터에서 확인된 사용감."""


class ProductAttributeKind(StrEnum):
    CATEGORY = "category"
    TEXTURE = "texture"
    SKIN_FEEL = "skin_feel"


class ProductTaxonomy(RagModel):
    """빈 목록은 해당 축의 필터 미지원이며 agent가 기본 분류를 보충하지 않는다."""

    version: str = Field(min_length=1)
    categories: list[ProductCategory] = Field(default_factory=list)
    textures: list[ProductTexture] = Field(default_factory=list)
    skin_feels: list[ProductSkinFeel] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_codes(self) -> Self:
        for kind in ProductAttributeKind:
            codes = [item.code for item in self.options(kind)]
            if len(codes) != len(set(codes)):
                raise ValueError(f"상품 분류 코드가 중복되었습니다: {kind.value}")
        return self

    def options(self, kind: ProductAttributeKind) -> list[ProductClassification]:
        if kind is ProductAttributeKind.CATEGORY:
            return list(self.categories)
        if kind is ProductAttributeKind.TEXTURE:
            return list(self.textures)
        return list(self.skin_feels)


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


class EvidenceSourceLane(StrEnum):
    EFFICACY = "efficacy"
    SAFETY = "safety"
    REGULATION = "regulation"


class EvidenceSourcePlan(RagModel):
    lane: EvidenceSourceLane
    primary_source_types: list[EvidenceSourceType] = Field(min_length=1)
    fallback_source_types: list[EvidenceSourceType] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_types(self) -> Self:
        primary = set(self.primary_source_types)
        fallback = set(self.fallback_source_types)
        if len(primary) != len(self.primary_source_types):
            raise ValueError("주 출처 목록에 중복된 출처 유형이 있습니다.")
        if len(fallback) != len(self.fallback_source_types):
            raise ValueError("보완 출처 목록에 중복된 출처 유형이 있습니다.")
        if primary.intersection(fallback):
            raise ValueError("주 출처와 보완 출처는 중복될 수 없습니다.")
        return self


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
    EVIDENCE = "evidence"
    CASE_USAGE_GUIDANCE = "case_usage_guidance"
    USER = "user"
    SERVICE_POLICY = "service_policy"


class RoutineRuleSourceKind(StrEnum):
    PRODUCT_DIRECTIONS = "product_directions"
    EVIDENCE = "evidence"
    # 기존 직렬화 값을 읽을 수 있어야 과거 루틴 요청과의 호환성이 깨지지 않는다.
    VERIFIED_EVIDENCE = "verified_evidence"
    UNREVIEWED_EVIDENCE = "unreviewed_evidence"
    CASE_USAGE_GUIDANCE = "case_usage_guidance"


class RoutineRuleType(StrEnum):
    ALLOWED_PERIOD = "allowed_period"
    MAX_FREQUENCY_PER_WEEK = "max_frequency_per_week"
    AVOID_SAME_PERIOD = "avoid_same_period"
    ORDER_BEFORE = "order_before"
    WARNING = "warning"


class RoutineRuleEnforcement(StrEnum):
    REQUIRED = "required"
    WARNING = "warning"


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
    version: str | None = Field(default=None, min_length=1)
    name: str = Field(min_length=1)
    category: ProductCategory | None = None
    texture: ProductTexture | None = None
    skin_feel: ProductSkinFeel | None = None
    ingredient_ids: list[str] = Field(default_factory=list)
    directions: str | None = Field(default=None, min_length=1)
    source_id: str = Field(min_length=1)
    checked_at: str = Field(min_length=1)
    is_demo: bool = True


class ProductSearchFilters(RagModel):
    category: ProductCategory | None = None
    texture: ProductTexture | None = None
    skin_feel: ProductSkinFeel | None = None
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
    source_plan: EvidenceSourcePlan | None = None
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


class OpenAiChatModel(StrEnum):
    GPT_4O_MINI = "gpt-4o-mini"


class LlmProvider(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    LOCAL = "local"


class EmbeddingProvider(StrEnum):
    OPENAI = "openai"
    LOCAL = "local"


class OpenAiEmbeddingModel(StrEnum):
    TEXT_EMBEDDING_3_SMALL = "text-embedding-3-small"


class LocalEmbeddingModel(StrEnum):
    BGE_M3 = "BAAI/bge-m3"


class LocalRerankerModel(StrEnum):
    BGE_RERANKER_V2_M3 = "BAAI/bge-reranker-v2-m3"


class LocalModelDevice(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"
    MPS = "mps"


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
    field_id: str = Field(min_length=1)
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
    reranker_score: float | None = Field(default=None, allow_inf_nan=False)


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


class RerankRequest(RagModel):
    query: str = Field(min_length=1)
    candidates: list[RetrievedChunk] = Field(min_length=1)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)


class RerankResult(RagModel):
    model: str = Field(min_length=1)
    chunks: list[RetrievedChunk] = Field(min_length=1)


class RagRetrievalPolicy(RagModel):
    # 새 브랜치의 특정 데이터셋에서 고른 임계값을 미확정 검색기에 강제하지 않는다.
    free_text_min_vector_similarity: float = Field(ge=-1, le=1)
    rrf_k: int = Field(default=60, gt=0)
    # 교차 인코더는 전체 말뭉치가 아니라 1차 검색 후보만 읽어 지연시간을 제한한다.
    rerank_candidate_limit: int = Field(default=DEFAULT_RERANK_CANDIDATE_LIMIT, ge=1)


class OpenAiChatConfig(RagModel):
    api_key: SecretStr
    model: OpenAiChatModel = OpenAiChatModel.GPT_4O_MINI
    timeout_seconds: float = Field(default=30, gt=0)
    max_retries: int = Field(default=1, ge=0)


class LocalChatConfig(RagModel):
    base_url: str = Field(default="http://localhost:11434/v1", min_length=1)
    model: str = Field(default="qwen 3.5:9B", min_length=1)
    api_key: SecretStr = Field(default=SecretStr("ollama"))
    timeout_seconds: float = Field(default=60, gt=0)
    max_retries: int = Field(default=1, ge=0)


class ChatModelConfig(RagModel):
    """채팅 의도 파싱 및 답변 생성에서 사용할 LLM 설정."""

    provider: LlmProvider = LlmProvider.OPENAI
    openai: OpenAiChatConfig | None = None
    local: LocalChatConfig = Field(default_factory=LocalChatConfig)

    @model_validator(mode="after")
    def validate_provider(self) -> Self:
        if self.provider is LlmProvider.OPENAI and self.openai is None:
            raise ValueError("OpenAI LLM을 선택하면 OpenAI 채팅 설정이 필요합니다.")
        return self

    def active_model(self) -> str:
        if self.provider is LlmProvider.OPENAI:
            if self.openai is None:
                raise ValueError("OpenAI 채팅 설정이 없습니다.")
            return self.openai.model.value
        return self.local.model


class OpenAiEmbeddingConfig(RagModel):
    api_key: SecretStr
    model: OpenAiEmbeddingModel = OpenAiEmbeddingModel.TEXT_EMBEDDING_3_SMALL
    # DB의 vector(1536) 계약과 API 결과가 어긋나면 저장 전에 실패하도록 차원을 고정한다.
    dimensions: int = Field(default=DEFAULT_OPENAI_EMBEDDING_DIMENSIONS, ge=1)
    batch_size: int = Field(default=DEFAULT_OPENAI_EMBEDDING_BATCH_SIZE, ge=1)
    timeout_seconds: float = Field(default=30, gt=0)
    max_retries: int = Field(default=1, ge=0)


class LocalEmbeddingConfig(RagModel):
    model: LocalEmbeddingModel = LocalEmbeddingModel.BGE_M3
    device: LocalModelDevice | None = None
    batch_size: int = Field(default=DEFAULT_EMBEDDING_BATCH_SIZE, ge=1)
    cache_folder: str | None = Field(default=None, min_length=1)
    local_files_only: bool = False


class TextEmbeddingConfig(RagModel):
    """운영에서 선택한 임베더와 각 구현의 설정을 함께 운반한다."""

    provider: EmbeddingProvider
    openai: OpenAiEmbeddingConfig | None = None
    local: LocalEmbeddingConfig = Field(default_factory=LocalEmbeddingConfig)

    @model_validator(mode="after")
    def validate_selected_provider(self) -> Self:
        if self.provider is EmbeddingProvider.OPENAI and self.openai is None:
            raise ValueError("OpenAI 임베딩을 선택하면 OpenAI 임베딩 설정이 필요합니다.")
        return self

    def output_dimensions(self) -> int:
        if self.provider is EmbeddingProvider.OPENAI:
            if self.openai is None:
                # 검증 이후 타입에서도 None 가능성이 남으므로 호출 경계에서 실패 원인을 보존한다.
                raise ValueError("OpenAI 임베딩 설정이 없습니다.")
            return self.openai.dimensions
        return BGE_M3_EMBEDDING_DIMENSIONS


class LocalRerankerConfig(RagModel):
    model: LocalRerankerModel = LocalRerankerModel.BGE_RERANKER_V2_M3
    device: LocalModelDevice | None = None
    batch_size: int = Field(default=DEFAULT_RERANKER_BATCH_SIZE, ge=1)
    max_length: int = Field(default=DEFAULT_RERANKER_MAX_LENGTH, ge=1)
    cache_folder: str | None = Field(default=None, min_length=1)
    local_files_only: bool = False


class GeneratedEvidenceStatement(RagModel):
    sentence: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class GeneratedEvidenceStatements(RagModel):
    claims: list[GeneratedEvidenceStatement] = Field(default_factory=list)


class EvidenceStatementGenerationRequest(RagModel):
    question: str = Field(min_length=1)
    records: list[EvidenceRecord] = Field(min_length=1)
    known_conditions: EvidenceConditions
    is_combination: bool = False


class EvidenceBackedStatement(RagModel):
    sentence: str = Field(min_length=1)
    sources: list[EvidenceRecord] = Field(min_length=1)


class IngredientVerificationResult(RagModel):
    claims: list[EvidenceBackedStatement] = Field(default_factory=list)
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
    reranker_model: str | None = Field(default=None, min_length=1)


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


class ProductCandidateLimitation(StrEnum):
    """상품 후보의 검증 한계이며 다음 사용자 요청의 검색 조건은 아니다."""

    DEMO_DATA = "개발용 상품 데이터이며 실제 제품 검증 결과가 아님"
    DIRECTIONS_UNKNOWN = "제품 사용법 미상"
    VERSION_UNKNOWN = "제품 버전 미상"
    INGREDIENT_EVIDENCE_ONLY = "성분 근거이며 완제품 자체의 임상 효과를 입증하지 않습니다."
    CLAIM_NOT_VERIFIED = "현재 연결된 공인 근거로 Claim을 충분히 확인하지 못했습니다."


class ProductCandidateSet(RagModel):
    candidate_set_id: str = Field(min_length=1)
    candidates: list[ProductCandidate] = Field(default_factory=list)
    is_demo: bool = True


class RoutineConstraint(RagModel):
    description: str = Field(min_length=1)
    source: ConstraintSource
    source_id: str | None = None


class CaseUsageGuidance(RagModel):
    """NIA Case의 사용법 구간 중 표준 성분과 연결된 참고 정보."""

    source_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    ingredient_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ingredient_ids(self) -> Self:
        if len(self.ingredient_ids) != len(set(self.ingredient_ids)):
            raise ValueError("Case 사용법의 성분 ID는 중복될 수 없습니다.")
        return self


class RoutineRuleSource(RagModel):
    source_id: str = Field(min_length=1)
    source_kind: RoutineRuleSourceKind
    text: str = Field(min_length=1)
    applicable_product_ids: list[str] = Field(min_length=1)


class RoutineRuleCandidate(RagModel):
    rule_type: RoutineRuleType
    product_ids: list[str] = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    allowed_periods: list[DayPeriod] = Field(default_factory=list)
    max_frequency_per_week: int | None = Field(default=None, ge=1, le=7)
    related_product_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rule_payload(self) -> Self:
        if self.rule_type is RoutineRuleType.ALLOWED_PERIOD and not self.allowed_periods:
            raise ValueError("allowed_period 규칙에는 허용 시간대가 필요합니다.")
        if (
            self.rule_type is RoutineRuleType.MAX_FREQUENCY_PER_WEEK
            and self.max_frequency_per_week is None
        ):
            raise ValueError("max_frequency_per_week 규칙에는 주당 횟수가 필요합니다.")
        if self.rule_type in {
            RoutineRuleType.AVOID_SAME_PERIOD,
            RoutineRuleType.ORDER_BEFORE,
        } and not self.related_product_ids:
            raise ValueError(f"{self.rule_type.value} 규칙에는 상대 제품이 필요합니다.")
        return self


class RoutineRule(RoutineRuleCandidate):
    source_kind: RoutineRuleSourceKind
    enforcement: RoutineRuleEnforcement


class RoutineRuleModelOutput(RagModel):
    rules: list[RoutineRuleCandidate] = Field(
        default_factory=list,
        max_length=MAX_ROUTINE_RULES,
    )


class RoutineRuleGenerationRequest(RagModel):
    user_request: str = Field(min_length=1)
    products: list[ProductRecord] = Field(min_length=1)
    sources: list[RoutineRuleSource] = Field(default_factory=list)


class RoutineRuleCompilationRequest(RagModel):
    products: list[ProductRecord] = Field(min_length=1)
    sources: list[RoutineRuleSource] = Field(default_factory=list)
    candidates: list[RoutineRuleCandidate] = Field(default_factory=list)


class RoutineRuleCompilationResult(RagModel):
    rules: list[RoutineRule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    rules: list[RoutineRule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    is_demo: bool = True


class RoutineDraftPlacement(RagModel):
    product_id: str = Field(min_length=1)
    weekday: Weekday
    period: DayPeriod
    order: int = Field(ge=1)
    reason: str = Field(min_length=1)


class RoutineDraftModelOutput(RagModel):
    placements: list[RoutineDraftPlacement] = Field(
        default_factory=list,
        max_length=MAX_ROUTINE_PLACEMENTS,
    )


class RoutineDraftGenerationRequest(RagModel):
    user_request: str = Field(min_length=1)
    products: list[ProductRecord] = Field(min_length=1)
    excluded_weekdays: list[Weekday] = Field(default_factory=list)
    frequency_per_week: int = Field(default=DEFAULT_ROUTINE_FREQUENCY, ge=1, le=7)
    rules: list[RoutineRule] = Field(default_factory=list)
    current_plan: RoutinePlan | None = None


class RoutinePlanRequest(RagModel):
    chat_room_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    products: list[ProductRecord] = Field(min_length=1)
    user_request: str = Field(min_length=1)
    excluded_weekdays: list[Weekday] = Field(default_factory=list)
    frequency_per_week: int = Field(default=DEFAULT_ROUTINE_FREQUENCY, ge=1, le=7)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    case_usage_guidance: list[CaseUsageGuidance] = Field(default_factory=list)
    current_plan: RoutinePlan | None = None


class RoutineValidationRequest(RagModel):
    plan: RoutinePlan
    products: list[ProductRecord] = Field(min_length=1)
    excluded_weekdays: list[Weekday] = Field(default_factory=list)
    frequency_per_week: int = Field(default=DEFAULT_ROUTINE_FREQUENCY, ge=1, le=7)


class RoutineValidationResult(RagModel):
    valid: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
