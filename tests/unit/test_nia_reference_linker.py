"""LLM/API 호출 없이 `NiaReferenceLinker`의 연결 조건만 검증한다.

자동 연결(cardinality 기반)을 비활성화했으므로, 어떤 조합을 넣어도 항상
`statement_links=[]`로 유지되는지 확인한다(reference 자체는 그대로 보존됨).
"""

from data.scripts.nia_reference_linker import NiaReferenceLinker


def _reference(raw: str) -> dict:
    return {"raw": raw, "reference_status": "unverified", "statement_links": []}


def _ingredient_effect_claim(statement_id: str) -> dict:
    return {
        "statement_id": statement_id,
        "statement_type": "ingredient_effect_claim",
        "source_spans": [
            {
                "json_path": "$.chain_of_thought[1].content",
                "quote": "성분 효과 설명",
                "start": 0,
                "end": 6,
            }
        ],
        "subject": {
            "raw_name": "NIACINAMIDE",
            "raw_name_ko": "나이아신아마이드",
            "ingredient_id": None,
            "matching_status": "unresolved",
        },
        "object": "미백",
        "concentration_raw": None,
    }


class TestNiaReferenceLinker:
    def test_does_not_link_even_when_counts_are_1to1(self) -> None:
        """이전에는 reference 1개 + ingredient statement 1개면 cardinality만으로
        연결됐다(local context 근거 없이). 자동 연결을 비활성화했으므로 이제는
        연결되지 않아야 한다."""
        references = [_reference("PMID:99999999")]
        statements = [_ingredient_effect_claim("T-S001")]

        linked = NiaReferenceLinker().link(references, statements)

        assert linked[0]["statement_links"] == []
        assert linked[0]["raw"] == "PMID:99999999"  # reference 자체는 보존됨

    def test_two_ingredient_claims_also_unlinked(self) -> None:
        references = [_reference("PMID:99999999")]
        statements = [
            _ingredient_effect_claim("T-S001"),
            _ingredient_effect_claim("T-S002"),
        ]

        linked = NiaReferenceLinker().link(references, statements)

        assert linked[0]["statement_links"] == []

    def test_placeholder_reference_never_linked(self) -> None:
        references = [
            {
                "raw": "DOI:10.xxxx/xxxxx",
                "reference_status": "placeholder_detected",
                "statement_links": [],
            }
        ]
        statements = [_ingredient_effect_claim("T-S001")]

        linked = NiaReferenceLinker().link(references, statements)

        assert linked[0]["statement_links"] == []
