"""Evidence coverage audit 의 타입. PubMed/CIR(과학적 근거) 기준이며 MFDS 는 다루지 않는다."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from models.evidence_document import EvidenceClaimTopic, EvidenceDocumentSourceType


class ScientificSource(StrEnum):
    """scientific coverage 에 세는 source. MFDS 는 규제 근거라 일부러 뺀다."""

    CIR = EvidenceDocumentSourceType.CIR.value
    PUBMED = EvidenceDocumentSourceType.PUBMED_ABSTRACT.value


class CoverageStatus(StrEnum):
    NO_SCIENTIFIC_EVIDENCE = "NO_SCIENTIFIC_EVIDENCE"
    SINGLE_SOURCE_ONLY = "SINGLE_SOURCE_ONLY"
    HAS_SCIENTIFIC_EVIDENCE = "HAS_SCIENTIFIC_EVIDENCE"  # CIR 과 PubMed 둘 다 있음


class PriorityTier(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class ScientificDocumentLink(BaseModel):
    """성분에 연결된 과학 근거 문서 한 건과, 그 문서에서 이 성분에 연결된 chunk 수."""

    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    document_id: UUID
    source: ScientificSource
    chunk_count: int
    claim_topics: tuple[str, ...]


class NiaRelevance(BaseModel):
    model_config = ConfigDict(frozen=True)

    nia_case_count: int = 0
    nia_answer_case_count: int = 0
    nia_concern_count: int = 0


class IngredientName(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    name_en: str | None
    name_ko: str


class CoverageRow(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    nia_case_count: int
    nia_answer_case_count: int
    nia_concern_count: int
    confirmed_product_count: int
    cir_document_count: int
    cir_chunk_count: int
    pubmed_document_count: int
    pubmed_chunk_count: int
    scientific_document_count: int
    scientific_chunk_count: int
    source_types_present: str
    efficacy_count: int
    safety_count: int
    usage_count: int
    concentration_count: int
    combination_count: int
    missing_topics: str
    coverage_status: CoverageStatus
    priority_tier: PriorityTier
    priority_reason: str


class TopicSourceRow(BaseModel):
    """ingredient × claim_topic × source 단위 문서 수."""

    ingredient_id: UUID
    ingredient_name: str
    claim_topic: str
    source: ScientificSource
    document_count: int


# 저장된 claim_topics 로 "없음"을 판정할 수 있는 topic. 과학 근거 문서에는 이 둘만 실제로 저장돼 있고
# 나머지(usage/concentration/combination)는 모든 성분이 0 이라 gap 으로 해석할 수 없다.
GAP_TOPICS: tuple[EvidenceClaimTopic, ...] = (
    EvidenceClaimTopic.EFFICACY,
    EvidenceClaimTopic.PRECAUTION,
)


class UniverseCategory(StrEnum):
    """audit universe 성분의 성격. 이름 규칙 + 기존 NIA/제품 수만으로 정한 제안이며 확정 분류가 아니다."""

    ACTIVE_OR_FUNCTIONAL = "active_or_functional"
    BOTANICAL_OR_FERMENT = "botanical_or_ferment"
    PEPTIDE_OR_PROTEIN = "peptide_or_protein"
    BASE_SOLVENT_HUMECTANT = "base_solvent_humectant"
    PRESERVATIVE_STABILIZER = "preservative_stabilizer"
    POLYMER_THICKENER = "polymer_thickener"
    SURFACTANT_EMULSIFIER_EMOLLIENT = "surfactant_emulsifier_emollient"
    PH_ADJUSTER_SALT = "ph_adjuster_salt"
    FRAGRANCE_ALLERGEN = "fragrance_allergen"
    FAMILY_OR_MECHANISM_TERM = "family_or_mechanism_term"


class CollectionDecision(StrEnum):
    COLLECT_BASELINE = "COLLECT_BASELINE"
    QA_PRIORITY = "QA_PRIORITY"  # 수집 대상이며 사람이 먼저 검수한다(수집 제외가 아님)
    DEFER = "DEFER"
    EXCLUDE_FROM_SCIENTIFIC_COLLECTION = "EXCLUDE_FROM_SCIENTIFIC_COLLECTION"


class UniverseRow(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    category: UniverseCategory
    decision: CollectionDecision
    decision_reason: str
    nia_case_count: int
    confirmed_product_count: int
    scientific_document_count: int
    current_priority_tier: PriorityTier
    families: str
    in_smoke_set: bool


class FamilyMemberRow(BaseModel):
    family: str
    ingredient_id: UUID
    ingredient_name: str
    nia_case_count: int
    confirmed_product_count: int
    scientific_document_count: int
