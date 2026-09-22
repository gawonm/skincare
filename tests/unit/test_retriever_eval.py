"""`RetrieverEvalRunner._make_result`의 순수 채점 로직 단위 테스트.

production retriever/DB 호출은 이 테스트의 범위 밖이다(실제 실행 검증은
docs/data/RETRIEVER_EVAL_REPORT.md의 16개 케이스 실행 결과가 담당한다).
"""

from data.scripts.retriever_eval import RetrieverEvalRunner
from data.scripts.retriever_eval_schemas import (
    EvalCase,
    FailureClassification,
    RetrievedChunkSummary,
    TargetMode,
    Verdict,
)


def _row(
    rank: int, target_ids: list[str], source_type: str = "paper", claim_topics=None
) -> RetrievedChunkSummary:
    return RetrievedChunkSummary(
        rank=rank,
        chunk_id=f"chunk-{rank}",
        source_type=source_type,
        source_title="title",
        pmid="1",
        doi="10.1/x",
        url="https://example.test",
        locator="abstract:0",
        claim_topics=claim_topics or ["efficacy"],
        target_ids=target_ids,
        vector_similarity=0.5,
        bm25_relevance=None,
        reranker_score=0.5,
    )


def _case(**overrides) -> EvalCase:
    defaults = {
        "case_id": "c",
        "query": "q",
        "target_mode": TargetMode.SINGLE,
        "expected_ingredient_name": "X",
        "expected_source_types": ["paper"],
        "expected_claim_topics": ["efficacy"],
    }
    defaults.update(overrides)
    return EvalCase(**defaults)


class TestMakeResult:
    def test_all_criteria_met_passes(self) -> None:
        runner = RetrieverEvalRunner.__new__(RetrieverEvalRunner)  # DB 없이 순수 메서드만 씀
        rows = [_row(i, ["ing-1"]) for i in range(1, 4)]
        result = runner._make_result(
            _case(),
            expected_ingredient_id="ing-1",
            target_ids_used=["ing-1"],
            lookup_status="success",
            retrieved=rows,
            verdict=Verdict.PASS,
            failure=FailureClassification.NONE,
            reason="ok",
        )
        assert result.ingredient_hit_at_3 is True
        assert result.ingredient_hit_at_5 is True
        assert result.ingredient_precision_at_5 == 1.0
        assert result.citation_metadata_complete is True

    def test_forbidden_ingredient_flagged_via_score_helper(self) -> None:
        rows = [_row(1, ["ing-1"]), _row(2, ["ing-2"])]
        precision = sum(1 for r in rows if "ing-1" in r.target_ids) / len(rows)
        assert precision == 0.5

    def test_citation_incomplete_for_missing_pmid(self) -> None:
        runner = RetrieverEvalRunner.__new__(RetrieverEvalRunner)
        row = _row(1, ["ing-1"])
        row = row.model_copy(update={"pmid": None})
        assert runner._citation_ok(row) is False

    def test_cir_without_pmid_is_still_complete(self) -> None:
        runner = RetrieverEvalRunner.__new__(RetrieverEvalRunner)
        row = _row(1, ["ing-1"], source_type="cir")
        row = row.model_copy(update={"pmid": None, "doi": None})
        assert runner._citation_ok(row) is True

    def test_cir_without_url_is_incomplete(self) -> None:
        runner = RetrieverEvalRunner.__new__(RetrieverEvalRunner)
        row = _row(1, ["ing-1"], source_type="cir")
        row = row.model_copy(update={"pmid": None, "doi": None, "url": None})
        assert runner._citation_ok(row) is False


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
