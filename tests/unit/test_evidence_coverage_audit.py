"""Evidence coverage audit 분류·집계 규칙. DB/외부 호출 없음."""

from uuid import uuid4

from data.scripts.evidence_coverage_audit import (
    NIA_HIGH_MIN_CASES,
    PRODUCT_HIGH_MIN,
    CoverageBuilder,
    CoverageClassifier,
)
from data.scripts.evidence_coverage_schemas import (
    CoverageStatus,
    IngredientName,
    NiaRelevance,
    PriorityTier,
    ScientificDocumentLink,
    ScientificSource,
)
from data.scripts.nia_product_backed_relevance import ProductBackedIngredientCount

_CLASSIFIER = CoverageClassifier()
_HIGH_NIA = NIA_HIGH_MIN_CASES
_HIGH_PRODUCT = PRODUCT_HIGH_MIN


def test_scientific_source_excludes_mfds() -> None:
    assert {s.value for s in ScientificSource} == {"cir", "pubmed_abstract"}


def test_status_classification() -> None:
    assert _CLASSIFIER.status(0, 0) is CoverageStatus.NO_SCIENTIFIC_EVIDENCE
    assert _CLASSIFIER.status(1, 0) is CoverageStatus.SINGLE_SOURCE_ONLY
    assert _CLASSIFIER.status(0, 2) is CoverageStatus.SINGLE_SOURCE_ONLY
    assert _CLASSIFIER.status(1, 2) is CoverageStatus.HAS_SCIENTIFIC_EVIDENCE


def test_priority_tiers() -> None:
    none = CoverageStatus.NO_SCIENTIFIC_EVIDENCE
    some = CoverageStatus.SINGLE_SOURCE_ONLY
    gap = ["efficacy"]
    assert _CLASSIFIER.priority(none, _HIGH_NIA, 1, gap)[0] is PriorityTier.P1
    assert _CLASSIFIER.priority(none, _HIGH_NIA, 0, gap)[0] is PriorityTier.P2
    assert _CLASSIFIER.priority(none, _HIGH_NIA - 1, 500, gap)[0] is PriorityTier.P4
    assert _CLASSIFIER.priority(some, 0, _HIGH_PRODUCT, gap)[0] is PriorityTier.P3
    assert _CLASSIFIER.priority(some, _HIGH_NIA, 0, [])[0] is PriorityTier.P4  # 공백 없음
    assert _CLASSIFIER.priority(some, 0, 0, gap)[0] is PriorityTier.P4  # relevance 낮음


def test_builder_counts_documents_and_topics_per_source() -> None:
    ingredient_id, doc_a, doc_b = uuid4(), uuid4(), uuid4()
    links = [
        ScientificDocumentLink(
            ingredient_id=ingredient_id,
            document_id=doc_a,
            source=ScientificSource.PUBMED,
            chunk_count=1,
            claim_topics=("efficacy", "precaution"),
        ),
        ScientificDocumentLink(
            ingredient_id=ingredient_id,
            document_id=doc_b,
            source=ScientificSource.CIR,
            chunk_count=5,
            claim_topics=("precaution",),
        ),
    ]
    names = [IngredientName(ingredient_id=ingredient_id, name_en="X", name_ko="엑스")]
    nia = {ingredient_id: NiaRelevance(nia_case_count=7)}
    products = [ProductBackedIngredientCount(ingredient_id=ingredient_id, product_count=3)]

    rows, topic_rows = CoverageBuilder(_CLASSIFIER).build(links, names, nia, products)

    row = rows[0]
    assert (row.cir_document_count, row.cir_chunk_count) == (1, 5)
    assert (row.pubmed_document_count, row.pubmed_chunk_count) == (1, 1)
    assert row.scientific_document_count == 2
    assert (row.efficacy_count, row.safety_count) == (1, 2)
    assert row.missing_topics == ""
    assert row.coverage_status is CoverageStatus.HAS_SCIENTIFIC_EVIDENCE
    assert row.confirmed_product_count == 3 and row.nia_case_count == 7
    assert len(topic_rows) == 3


def test_builder_marks_gaps_when_no_links() -> None:
    ingredient_id = uuid4()
    names = [IngredientName(ingredient_id=ingredient_id, name_en=None, name_ko="한글")]
    rows, _ = CoverageBuilder(_CLASSIFIER).build([], names, {}, [])
    assert rows[0].ingredient_name == "한글"
    assert rows[0].missing_topics == "missing_efficacy;missing_safety"
    assert rows[0].coverage_status is CoverageStatus.NO_SCIENTIFIC_EVIDENCE
