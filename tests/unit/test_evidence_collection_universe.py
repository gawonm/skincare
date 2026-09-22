"""수집 자격 규칙과 family 탐지. DB/외부 호출 없음."""

from uuid import uuid4

from data.scripts.evidence_collection_universe import (
    MIN_PRODUCTS_FOR_BASELINE,
    QA_NIA_MIN_CASES,
    QA_SAMPLE_PER_STRATUM,
    SMOKE_INGREDIENTS,
    CollectionEligibility,
    FamilyDetector,
    SafetyReviewRegistry,
    StratifiedQaSampler,
)
from data.scripts.evidence_coverage_schemas import (
    CollectionDecision,
    CoverageRow,
    CoverageStatus,
    PriorityTier,
    ReviewFlag,
    SafetyRegistryEntry,
    SafetyReviewStatus,
    UniverseCategory,
    UniverseRow,
)

_E = CollectionEligibility()
_COLLECT = {CollectionDecision.COLLECT_BASELINE, CollectionDecision.QA_PRIORITY}


def _row(
    name: str,
    nia: int = 0,
    products: int = 0,
    tier: PriorityTier = PriorityTier.P4,
    evidence: int = 0,
) -> CoverageRow:
    return CoverageRow(
        ingredient_id=uuid4(),
        ingredient_name=name,
        nia_case_count=nia,
        nia_answer_case_count=0,
        nia_concern_count=0,
        confirmed_product_count=products,
        cir_document_count=0,
        cir_chunk_count=0,
        pubmed_document_count=0,
        pubmed_chunk_count=0,
        scientific_document_count=evidence,
        scientific_chunk_count=0,
        source_types_present="",
        efficacy_count=0,
        safety_count=0,
        usage_count=0,
        concentration_count=0,
        combination_count=0,
        missing_topics="",
        coverage_status=CoverageStatus.NO_SCIENTIFIC_EVIDENCE,
        priority_tier=tier,
        priority_reason="",
    )


def _decide(row: CoverageRow, eligibility: CollectionEligibility = _E) -> CollectionDecision:
    return eligibility.decide(row, eligibility.category(row.ingredient_name)).decision


def test_category_rules_order() -> None:
    assert _E.category("Glycerin") is UniverseCategory.BASE_SOLVENT_HUMECTANT
    assert _E.category("Hexapeptide-2") is UniverseCategory.PEPTIDE_OR_PROTEIN
    # 히알루론산 가교체는 crosspolymer 규칙보다 hyaluron 규칙이 먼저라 active 로 남는다
    assert _E.category("Sodium Hyaluronate Crosspolymer") is UniverseCategory.ACTIVE_OR_FUNCTIONAL
    assert _E.category("BHA") is UniverseCategory.FAMILY_OR_MECHANISM_TERM
    assert _E.category("Centella Asiatica Extract") is UniverseCategory.BOTANICAL_OR_FERMENT
    assert _E.category("Carbomer") is UniverseCategory.POLYMER_THICKENER
    assert _E.category("Niacinamide") is UniverseCategory.ACTIVE_OR_FUNCTIONAL


def test_qa_reclassification() -> None:
    # UV 필터는 preservative 의 "benzoate" 규칙보다 먼저라 잘리지 않는다
    assert _E.category("Diethylamino Hydroxybenzoyl Hexyl Benzoate") is UniverseCategory.UV_FILTER
    assert (
        _E.category("Bis-Ethylhexyloxyphenol Methoxyphenyl Triazine") is UniverseCategory.UV_FILTER
    )
    assert _E.category("Boron Nitride") is UniverseCategory.FILLER_POWDER
    assert _E.category("Algin") is UniverseCategory.POLYMER_THICKENER
    assert _E.category("Triethyl Citrate") is UniverseCategory.FORMULATION_AID
    assert _E.category("Butyloctyl Salicylate") is UniverseCategory.FORMULATION_AID
    assert _E.category("Sodium Citrate") is UniverseCategory.PH_ADJUSTER_SALT
    assert _E.category("Elaeis Guineensis (Palm) Oil") is UniverseCategory.CARRIER_OIL
    assert _E.category("Vitis Vinifera (Grape) Seed Oil") is UniverseCategory.CARRIER_OIL


def test_manual_decision_overrides_rules() -> None:
    assert _decide(_row("Salicylic Acid", nia=3, products=178)) is CollectionDecision.QA_PRIORITY
    mineral = _row("Mineral Salts", nia=1268, products=11, tier=PriorityTier.P1)
    assert _decide(mineral) is CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION


def test_formulation_categories_excluded_unless_nia_mention() -> None:
    assert _decide(_row("Carbomer", products=616)) is (
        CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION
    )
    assert _decide(_row("Carbomer", nia=5, products=616)) is CollectionDecision.DEFER


def test_humectant_and_amino_acid_deferred_not_excluded() -> None:
    assert _decide(_row("Sorbitol", products=93)) is CollectionDecision.DEFER
    assert _decide(_row("Lysine", products=81)) is CollectionDecision.DEFER


def test_irritant_surfactant_deferred_with_safety_flag() -> None:
    row = _row("Sodium Laureth Sulfate", products=4)
    decided = _E.decide(row, _E.category(row.ingredient_name))
    assert decided.decision is CollectionDecision.DEFER
    assert ReviewFlag.SAFETY_RELEVANT in decided.flags


def test_long_tail_deferred_and_relevant_collected() -> None:
    assert _decide(_row("Example Active X", products=MIN_PRODUCTS_FOR_BASELINE - 1)) is (
        CollectionDecision.DEFER
    )
    assert _decide(_row("Example Active X", products=MIN_PRODUCTS_FOR_BASELINE)) is (
        CollectionDecision.COLLECT_BASELINE
    )
    assert _decide(_row("Example Active X", nia=QA_NIA_MIN_CASES, products=1)) is (
        CollectionDecision.QA_PRIORITY
    )


def test_uv_filter_is_collected() -> None:
    row = _row("Bis-Ethylhexyloxyphenol Methoxyphenyl Triazine", products=8)
    assert _decide(row) is CollectionDecision.COLLECT_BASELINE


def test_botanical_and_carrier_oil_need_nia_or_evidence() -> None:
    # 제품 수가 아무리 많아도 NIA·기존 근거가 없으면 수집하지 않는다
    assert (
        _decide(_row("Example Officinalis Leaf Extract", products=500)) is CollectionDecision.DEFER
    )
    assert _decide(_row("Example Seed Oil", products=500)) is CollectionDecision.DEFER
    assert _decide(_row("Example Officinalis Leaf Extract", nia=1, products=6)) in _COLLECT
    assert _decide(_row("Example Officinalis Leaf Extract", products=6, evidence=1)) in _COLLECT


def test_nia_only_without_product_goes_to_review_not_collect() -> None:
    for name in ("Achyranthes Bidentata Root Extract", "Chitin", "Example Active X"):
        row = _row(name, nia=504, products=0)
        assert _decide(row) is CollectionDecision.NAME_OR_LINEAGE_REVIEW
    # NIA 가 0 이면 제품이 없어도 이 경로가 아니라 long tail 규칙이다
    assert _decide(_row("Example Active X", nia=0, products=0)) is CollectionDecision.DEFER


def test_safety_registry_candidate_is_not_auto_collected_and_approved_is() -> None:
    candidate = _row("Lavandula Angustifolia (Lavender) Oil", products=141)
    approved = _row("Mentha Piperita (Peppermint) Leaf Extract", products=20)
    registry = SafetyReviewRegistry(
        [
            SafetyRegistryEntry(
                ingredient_id=candidate.ingredient_id,
                ingredient_name=candidate.ingredient_name,
                group="Lavandula",
                status=SafetyReviewStatus.CANDIDATE,
            ),
            SafetyRegistryEntry(
                ingredient_id=approved.ingredient_id,
                ingredient_name=approved.ingredient_name,
                group="Mentha",
                status=SafetyReviewStatus.APPROVED,
                note="검토 승인",
            ),
        ]
    )
    eligibility = CollectionEligibility(registry)
    flagged = eligibility.decide(candidate, eligibility.category(candidate.ingredient_name))
    assert flagged.decision is CollectionDecision.DEFER
    assert ReviewFlag.SAFETY_REVIEW_CANDIDATE in flagged.flags
    assert _decide(approved, eligibility) is CollectionDecision.COLLECT_BASELINE
    # 승인 항목을 뺀 규칙 단독 평가에서는 승인이 사라진다
    without = CollectionEligibility(registry.without_approvals())
    assert _decide(approved, without) is CollectionDecision.DEFER


def test_family_detection_keeps_ids_separate() -> None:
    detector = FamilyDetector()
    assert detector.families_of("Sodium Hyaluronate") == ["hyaluronic"]
    assert detector.families_of("Polylactic Acid") == []
    assert "retinoid" in detector.families_of("Retinal")
    assert set(detector.families_of("Salicylic Acid")) == {"bha_aha"}
    assert set(detector.families_of("3-O-Ethyl Ascorbic Acid")) == {"vitamin_c"}


def test_smoke_set_size_and_required_members() -> None:
    assert 10 <= len(SMOKE_INGREDIENTS) <= 20
    for name in (
        "Niacinamide",
        "Retinol",
        "Salicylic Acid",
        "Ascorbic Acid",
        "Hexapeptide-2",
        "BHA",
    ):
        assert name in SMOKE_INGREDIENTS


def test_qa_sampler_is_stratified_and_deterministic() -> None:
    universe = [
        UniverseRow(
            ingredient_id=uuid4(),
            ingredient_name=f"X{i}",
            category=UniverseCategory.ACTIVE_OR_FUNCTIONAL,
            decision=d,
            decision_reason="",
            nia_case_count=0,
            confirmed_product_count=0,
            scientific_document_count=0,
            current_priority_tier=PriorityTier.P4,
            flags="",
            families="",
            in_smoke_set=False,
        )
        for d in CollectionDecision
        for i in range(30)
    ]
    first = StratifiedQaSampler().sample(universe)
    assert first == StratifiedQaSampler().sample(universe)
    labels = [label for label, _ in first]
    assert labels.count("DEFER") == QA_SAMPLE_PER_STRATUM
    assert labels.count("collect_active") == QA_SAMPLE_PER_STRATUM
    assert labels.count("collect_botanical") == 0  # 이 입력에는 botanical 이 없다
