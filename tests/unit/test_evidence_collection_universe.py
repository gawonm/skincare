"""수집 자격 규칙과 family 탐지. DB/외부 호출 없음."""

from uuid import uuid4

from data.scripts.evidence_collection_universe import (
    MIN_PRODUCTS_FOR_BASELINE,
    QA_NIA_MIN_CASES,
    SMOKE_INGREDIENTS,
    CollectionEligibility,
    FamilyDetector,
)
from data.scripts.evidence_coverage_schemas import (
    CollectionDecision,
    CoverageRow,
    CoverageStatus,
    PriorityTier,
    UniverseCategory,
)

_E = CollectionEligibility()


def _row(
    name: str, nia: int = 0, products: int = 0, tier: PriorityTier = PriorityTier.P4
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
        scientific_document_count=0,
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


def test_category_rules_order() -> None:
    assert _E.category("Glycerin") is UniverseCategory.BASE_SOLVENT_HUMECTANT
    assert _E.category("Hexapeptide-2") is UniverseCategory.PEPTIDE_OR_PROTEIN
    # 히알루론산 가교체는 crosspolymer 규칙보다 hyaluron 규칙이 먼저라 active 로 남는다
    assert _E.category("Sodium Hyaluronate Crosspolymer") is UniverseCategory.ACTIVE_OR_FUNCTIONAL
    assert _E.category("BHA") is UniverseCategory.FAMILY_OR_MECHANISM_TERM
    assert _E.category("Centella Asiatica Extract") is UniverseCategory.BOTANICAL_OR_FERMENT
    assert _E.category("Carbomer") is UniverseCategory.POLYMER_THICKENER
    assert _E.category("Niacinamide") is UniverseCategory.ACTIVE_OR_FUNCTIONAL


def test_manual_decision_overrides_rules() -> None:
    row = _row("Salicylic Acid", nia=3, products=178)
    decision, _ = _E.decide(row, _E.category(row.ingredient_name))
    assert decision is CollectionDecision.QA_PRIORITY
    row = _row("Mineral Salts", nia=1268, products=11, tier=PriorityTier.P1)
    assert (
        _E.decide(row, _E.category(row.ingredient_name))[0]
        is CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION
    )


def test_non_active_excluded_unless_nia_mention() -> None:
    plain = _row("Butylene Glycol", products=1784)
    assert (
        _E.decide(plain, _E.category(plain.ingredient_name))[0]
        is CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION
    )
    mentioned = _row("Butylene Glycol", nia=5, products=1784)
    assert (
        _E.decide(mentioned, _E.category(mentioned.ingredient_name))[0] is CollectionDecision.DEFER
    )


def test_long_tail_deferred_and_relevant_collected() -> None:
    tail = _row("Example Active X", products=MIN_PRODUCTS_FOR_BASELINE - 1)
    assert _E.decide(tail, _E.category(tail.ingredient_name))[0] is CollectionDecision.DEFER
    ok = _row("Example Active X", products=MIN_PRODUCTS_FOR_BASELINE)
    assert _E.decide(ok, _E.category(ok.ingredient_name))[0] is CollectionDecision.COLLECT_BASELINE
    high = _row("Example Active X", nia=QA_NIA_MIN_CASES)
    assert _E.decide(high, _E.category(high.ingredient_name))[0] is CollectionDecision.QA_PRIORITY


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


def test_botanical_gate() -> None:
    from data.scripts.evidence_collection_universe import BOTANICAL_MIN_PRODUCTS

    name = "Example Officinalis Leaf Extract"
    low = _row(name, products=BOTANICAL_MIN_PRODUCTS - 1)
    assert _E.decide(low, _E.category(name))[0] is CollectionDecision.DEFER
    assert _E.decide(_row(name, products=BOTANICAL_MIN_PRODUCTS), _E.category(name))[0] is (
        CollectionDecision.COLLECT_BASELINE
    )
    # NIA 언급이 있으면 제품이 적어도 gate 를 통과한다
    assert _E.decide(_row(name, nia=1, products=1), _E.category(name))[0] is (
        CollectionDecision.COLLECT_BASELINE
    )


def test_qa_sampler_is_stratified_and_deterministic() -> None:
    from data.scripts.evidence_collection_universe import QA_SAMPLE_PER_STRATUM, StratifiedQaSampler
    from data.scripts.evidence_coverage_schemas import UniverseRow

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
