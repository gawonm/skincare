"""50-smoke 표본 추출 규칙. DB/외부 호출 없음."""

from uuid import uuid4

from data.scripts.evidence_coverage_schemas import (
    CollectionDecision,
    PriorityTier,
    UniverseCategory,
    UniverseRow,
)
from data.scripts.pubmed_smoke_runner import (
    EXISTING_SMOKE,
    STRATUM_ACTIVE,
    STRATUM_BOTANICAL,
    STRATUM_EXISTING,
    STRATUM_QA,
    STRATUM_UV,
    SmokeSampler,
)


def _u(name: str, category: UniverseCategory, decision: CollectionDecision) -> UniverseRow:
    return UniverseRow(
        ingredient_id=uuid4(),
        ingredient_name=name,
        category=category,
        decision=decision,
        decision_reason="",
        nia_case_count=0,
        confirmed_product_count=10,
        scientific_document_count=0,
        current_priority_tier=PriorityTier.P4,
        flags="",
        families="",
        in_smoke_set=False,
    )


def _universe(uv_count: int = 8) -> list[UniverseRow]:
    active = UniverseCategory.ACTIVE_OR_FUNCTIONAL
    collect = CollectionDecision.COLLECT_BASELINE
    rows = [_u(n, active, collect) for n in EXISTING_SMOKE]
    rows += [_u(f"Active{i}", active, collect) for i in range(60)]
    rows += [_u(f"Bot{i}", UniverseCategory.BOTANICAL_OR_FERMENT, collect) for i in range(20)]
    rows += [_u(f"Uv{i}", UniverseCategory.UV_FILTER, collect) for i in range(uv_count)]
    rows += [_u(f"Qa{i}", active, CollectionDecision.QA_PRIORITY) for i in range(15)]
    return rows


def test_composition_is_10_20_8_5_7_without_duplicates() -> None:
    picked, notes = SmokeSampler().sample(_universe())
    strata = [s for s, _ in picked]
    assert strata.count(STRATUM_EXISTING) == 10
    assert strata.count(STRATUM_ACTIVE) == 20
    assert strata.count(STRATUM_BOTANICAL) == 8
    assert strata.count(STRATUM_UV) == 5
    assert strata.count(STRATUM_QA) == 7
    names = [u.ingredient_name for _, u in picked]
    assert len(names) == len(set(names)) == 50
    assert notes == []


def test_sampling_is_deterministic_for_same_input() -> None:
    universe = _universe()
    first = [u.ingredient_name for _, u in SmokeSampler().sample(universe)[0]]
    assert first == [u.ingredient_name for _, u in SmokeSampler().sample(universe)[0]]


def test_shortfall_is_filled_from_active_and_reported() -> None:
    picked, notes = SmokeSampler().sample(_universe(uv_count=2))
    strata = [s for s, _ in picked]
    assert strata.count(STRATUM_UV) == 2
    assert strata.count(STRATUM_ACTIVE) == 23  # 20 + 부족한 UV 3
    assert len(picked) == 50
    assert notes and "collect_uv_filter" in notes[0]
