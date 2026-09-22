"""PubMed full collection 자동 리포트 보조 로직. 파일 입출력·외부 호출 없음."""

from uuid import uuid4

import pytest

from data.scripts.evidence_coverage_schemas import (
    CollectionDecision,
    PriorityTier,
    UniverseCategory,
    UniverseRow,
)
from data.scripts.pubmed_collection_report import NameBoundaryChecker, PubmedCollectionReporter
from data.scripts.pubmed_full_collection import FullCollectionPlan


@pytest.mark.parametrize(
    ("title", "names", "expected"),
    [
        ("Prevention of poison ivy dermatitis by quaternium-18 bentonite.", ["Bentonite"], True),
        (
            "Mitigation of erythema by para-hydroxycinnamic acid in human skin",
            ["Hydroxycinnamic Acid"],
            True,
        ),
        ("Use of retinol palmitate on skin", ["Retinol"], True),
        ("The effect of 2% niacinamide on facial sebum production.", ["Niacinamide"], False),
        ("Topical niacinamide treatment for lupus", ["Niacinamide"], False),
        ("Clinical trial of 10% all-trans retinol gel", ["Retinol"], False),
        ("Efficacy of a Salicylic Acid-Containing Gel on acne", ["Salicylic Acid"], False),
    ],
)
def test_name_boundary_checker(title: str, names: list[str], expected: bool) -> None:
    assert NameBoundaryChecker().suspicious(title, names) is expected


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


def test_full_plan_excludes_botanical_and_non_collectable() -> None:
    universe = [
        _u("A", UniverseCategory.ACTIVE_OR_FUNCTIONAL, CollectionDecision.COLLECT_BASELINE),
        _u("B", UniverseCategory.UV_FILTER, CollectionDecision.QA_PRIORITY),
        _u("Bot", UniverseCategory.BOTANICAL_OR_FERMENT, CollectionDecision.COLLECT_BASELINE),
        _u("D", UniverseCategory.ACTIVE_OR_FUNCTIONAL, CollectionDecision.DEFER),
        _u("E", UniverseCategory.ACTIVE_OR_FUNCTIONAL, CollectionDecision.NAME_OR_LINEAGE_REVIEW),
    ]
    targets, botanical = FullCollectionPlan().eligible(universe)
    assert sorted(t.ingredient_name for t in targets) == ["A", "B"]
    assert botanical == 1


def test_reporter_class_is_importable() -> None:
    assert PubmedCollectionReporter is not None
