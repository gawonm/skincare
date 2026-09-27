"""NIA Case 단일 질의 전략 비교 규칙을 검증한다."""

from pathlib import Path
from typing import ClassVar

import pytest

from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
)
from tests.agent.evaluate_nia_case_query_strategy import (
    NiaCaseDenseQueryHit,
    NiaCaseDenseQueryMetricCalculator,
    NiaCaseDenseQueryStrategyReport,
    NiaCaseQueryStrategy,
    NiaCaseQueryVariantBuilder,
)
from tests.agent.nia_case_semantic_candidate_pool import CandidatePoolArtifactLoader
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
)


class TestNiaCaseQueryVariantBuilder:
    QUERY_PATH: ClassVar[Path] = NiaCaseCorpusRelativeEvaluationCli.QUERY_PATH

    def test_builds_one_summary_and_one_context_query_per_evaluation(self) -> None:
        queries = NiaCaseSemanticEvaluationQueryLoader().load(self.QUERY_PATH).items

        variants = NiaCaseQueryVariantBuilder().build(queries)

        assert len(variants) == 72
        for query in queries:
            selected = [
                item
                for item in variants
                if item.evaluation_id == query.evaluation_id
            ]
            assert [item.strategy for item in selected] == [
                NiaCaseQueryStrategy.CONCERN_SUMMARY,
                NiaCaseQueryStrategy.PROFILE_SUMMARY,
                NiaCaseQueryStrategy.CONTEXT_PRESERVED,
            ]
            assert selected[2].query == query.query
            assert selected[0].query.endswith("피부 관련 성분 및 주의사항")
            assert selected[1].query.endswith("피부 관련 성분 및 주의사항")
            assert all(
                concern.value in selected[0].query
                for concern in [
                    *query.primary_concerns,
                    *query.secondary_concerns,
                ]
            )


class TestNiaCaseDenseQueryMetricCalculator:
    def test_calculates_top20_and_top40_anchor_metrics_separately(self) -> None:
        hits = [
            NiaCaseDenseQueryHit(
                case_id=f"case_{rank}",
                rank=rank,
                similarity=1.0 - rank / 100.0,
            )
            for rank in range(1, 41)
        ]

        metrics = NiaCaseDenseQueryMetricCalculator().calculate(
            hits=hits,
            relevant_anchor_ids=["case_2", "case_30", "case_missing"],
        )

        assert metrics.anchor_success_at_20 is True
        assert metrics.anchor_recall_at_20 == pytest.approx(1 / 3)
        assert metrics.anchor_success_at_40 is True
        assert metrics.anchor_recall_at_40 == pytest.approx(2 / 3)
        assert metrics.reciprocal_rank_at_40 == pytest.approx(0.5)
        assert metrics.retrieved_relevant_anchor_ids == ["case_2", "case_30"]


class TestNiaCaseDenseQueryStrategyArtifact:
    SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_query_strategy_dense_summary_20260926_1709_v1.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )

    def test_records_complete_dense_comparison_result(self) -> None:
        report = NiaCaseDenseQueryStrategyReport.model_validate_json(
            self.SUMMARY_PATH.read_text(encoding="utf-8").strip()
        )
        aggregates = {
            (item.strategy.value, item.slice.value): item
            for item in report.aggregates
        }

        assert report.query_count == 24
        assert len(report.results) == 72
        assert len(report.pairwise) == 24
        assert report.context_preserved_win_count == 17
        assert report.profile_summary_win_count == 3
        assert report.tie_count == 4
        assert aggregates[("concern_summary", "all")].anchor_recall_at_40 == (
            pytest.approx(0.1984848485)
        )
        assert aggregates[("context_preserved", "all")].anchor_recall_at_40 == (
            pytest.approx(0.4810606061)
        )
        assert aggregates[("profile_summary", "all")].anchor_recall_at_40 == (
            pytest.approx(0.2212121212)
        )

    def test_context_strategy_matches_live_dense_top40_membership(self) -> None:
        report = NiaCaseDenseQueryStrategyReport.model_validate_json(
            self.SUMMARY_PATH.read_text(encoding="utf-8").strip()
        )
        context_by_id = {
            item.evaluation_id: item
            for item in report.results
            if item.strategy is NiaCaseQueryStrategy.CONTEXT_PRESERVED
        }
        live_items = CandidatePoolArtifactLoader().load_internal(
            self.LIVE_POOL_PATH
        )

        assert len(context_by_id) == len(live_items) == 24
        for live_item in live_items:
            live_top40 = {
                candidate.case_id
                for candidate in live_item.candidates
                if candidate.dense_rank is not None and candidate.dense_rank <= 40
            }
            context_top40 = {
                item.case_id for item in context_by_id[live_item.evaluation_id].hits
            }
            assert context_by_id[live_item.evaluation_id].query == live_item.query
            assert context_top40 == live_top40
