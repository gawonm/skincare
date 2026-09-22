"""CIR registry 후보 우선순위 규칙과 게재 기록 매칭. 외부 호출 없음."""

from datetime import date

from data.scripts.cir_registry_candidates import CirCandidateBuilder, CirPublishedReportFinder
from data.scripts.evidence_collector_schemas import PubmedRecord


def _matrix(
    pid: str, products: int, nia: int = 0, cir: int = 0, docs: int = 0, safety: int = 0
) -> dict[str, str]:
    return {
        "ingredient_id": pid,
        "confirmed_product_count": str(products),
        "nia_case_count": str(nia),
        "cir_document_count": str(cir),
        "scientific_document_count": str(docs),
        "safety_count": str(safety),
    }


def _universe(pid: str, name: str, decision: str = "COLLECT_BASELINE") -> dict[str, str]:
    return {
        "ingredient_id": pid,
        "ingredient_name": name,
        "decision": decision,
        "category": "active_or_functional",
    }


def _bundle(ingredient_id: str, topics: list[str]) -> dict[str, object]:
    return {"document": {"ingredient_ids": [ingredient_id], "claim_topics": topics}}


def test_priority_rules() -> None:
    matrix = {
        "a": _matrix("a", 500),  # 근거 0 + 높음 -> P1
        "b": _matrix("b", 300),  # KEEP 있음 + 높음 -> P2
        "c": _matrix("c", 30),  # 근거 0 + 제품 20 이상이나 높지 않음 -> P3
        "d": _matrix("d", 500, cir=1),  # 이미 CIR 있음 -> 제외
        "e": _matrix("e", 5),  # 낮음 -> 제외
    }
    universe = {k: _universe(k, k.upper()) for k in matrix}
    result = CirCandidateBuilder().build(matrix, universe, [_bundle("b", ["efficacy"])])
    priorities = {c.ingredient: c.priority for c in result}
    assert priorities == {"A": "P1", "B": "P2", "C": "P3"}
    b = next(c for c in result if c.ingredient == "B")
    assert b.missing_claim_topics == "precaution"
    assert b.pubmed_keep_count == 1


class _FakeSource:
    def __init__(self, records: list[PubmedRecord]) -> None:
        self._records = records

    def search(self, query: str, retmax: int) -> list[str]:
        return [r.pmid for r in self._records]

    def fetch(self, pmids: list[str]) -> list[PubmedRecord]:
        return self._records


def _rec(pmid: str, title: str, abstract: str = "") -> PubmedRecord:
    return PubmedRecord(
        pmid=pmid,
        doi=None,
        title=title,
        abstract=abstract,
        journal="Int J Toxicol",
        publication_date=date(2024, 1, 1),
        publication_types=[],
        mesh_terms=[],
        authors=[],
    )


def test_finder_accepts_title_match_and_cir_style_abstract_match_only() -> None:
    records = [
        _rec("1", "Safety Assessment of Adenosine as Used in Cosmetics."),
        _rec(
            "2", "Unrelated liver study", "adenosine was measured"
        ),  # 초록만 일치하고 CIR 제목 형식도 아님
        _rec(
            "3",
            "Safety Assessment of Glycolactones as Used in Cosmetics.",
            "gluconolactone is a glycolactone",
        ),
    ]
    finder = CirPublishedReportFinder(_FakeSource(records))
    adenosine = finder.find("Adenosine")
    assert [r["pmid"] for r in adenosine.reports] == ["1"]
    gluconolactone = finder.find("Gluconolactone")
    assert [r["pmid"] for r in gluconolactone.reports] == ["3"]
    assert gluconolactone.reports[0]["matched_in"] == "abstract"
