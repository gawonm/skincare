"""NIA Case 코퍼스 상대 검색 관련성 등급 규칙을 검증한다."""

from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError

from tests.agent.adjudicate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeAdjudication,
    NiaCaseCorpusRelativeGoldenAdjudicator,
)
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeGoldenCase,
)
from tests.agent.evaluate_nia_case_corpus_relative_live_v3 import (
    CorpusRelativeLiveEvaluationStatus,
    NiaCaseCorpusRelativeLiveMarkdownReporter,
    NiaCaseCorpusRelativeLiveProbeItem,
    NiaCaseCorpusRelativeLiveRunSummary,
)
from tests.agent.finalize_nia_case_corpus_relative_live_v3 import (
    NiaCaseCorpusRelativeLiveGoldenExpander,
)
from tests.agent.nia_case_corpus_relative_audit import (
    CorpusRelativeAuditSamplingPolicy,
    NiaCaseCorpusRelativeAuditEvaluator,
    NiaCaseCorpusRelativeAuditSampler,
)
from tests.agent.nia_case_corpus_relative_golden import (
    CorpusRelativeAnchorStratum,
    CorpusRelativeEvaluationId,
    NiaCaseCorpusRelativeAnchorSampler,
    NiaCaseCorpusRelativeQuerySelector,
)
from tests.agent.nia_case_corpus_relevance_review import (
    NiaCaseCorpusRelevanceReviewBuilder,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    CorpusConcernFitScore,
    CorpusContextFitScore,
    CorpusDirectionConflictCode,
    CorpusRelevanceGrade,
    CorpusRelevanceReasonCode,
    CorpusRequestFitScore,
    NiaCaseCorpusRelevanceJudgment,
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import CandidatePoolArtifactLoader
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
    SemanticEvaluationCohort,
)
from tests.agent.nia_case_semantic_final_golden import NiaCaseSemanticGoldenArtifact
from tests.agent.recheck_nia_case_corpus_relative_live_reranker import (
    NiaCaseDenseBaselineChecker,
    NiaCaseRerankerRepeatChecker,
)


class TestNiaCaseCorpusRelevanceJudgment:
    def test_direct_concern_request_and_context_is_highly_relevant(self) -> None:
        judgment = NiaCaseCorpusRelevanceJudgment(
            review_key="0123456789abcdef",
            concern_fit=CorpusConcernFitScore.DIRECT,
            context_fit=CorpusContextFitScore.PARTIAL,
            request_fit=CorpusRequestFitScore.DIRECT,
            reason_codes=[
                CorpusRelevanceReasonCode.PRIMARY_CONCERN_MATCH,
                CorpusRelevanceReasonCode.REQUEST_DIRECTION_MATCH,
            ],
            relevance_grade=CorpusRelevanceGrade.HIGHLY_RELEVANT,
            note="핵심 고민과 요청 방향이 직접 일치하고 피부 상태도 일부 일치한다.",
        )

        assert judgment.relevance_grade is CorpusRelevanceGrade.HIGHLY_RELEVANT

    def test_direct_concern_and_partial_request_is_relevant(self) -> None:
        judgment = NiaCaseCorpusRelevanceJudgment(
            review_key="1111111111111111",
            concern_fit=CorpusConcernFitScore.DIRECT,
            context_fit=CorpusContextFitScore.NONE,
            request_fit=CorpusRequestFitScore.PARTIAL,
            reason_codes=[CorpusRelevanceReasonCode.PRIMARY_CONCERN_MATCH],
            relevance_grade=CorpusRelevanceGrade.RELEVANT,
            note="핵심 고민은 같지만 사용자가 요청한 세부 방향은 일부만 다룬다.",
        )

        assert judgment.relevance_grade is CorpusRelevanceGrade.RELEVANT

    def test_adjacent_concern_with_same_state_and_request_is_relevant(self) -> None:
        judgment = NiaCaseCorpusRelevanceJudgment(
            review_key="2222222222222222",
            concern_fit=CorpusConcernFitScore.ADJACENT,
            context_fit=CorpusContextFitScore.STRONG,
            request_fit=CorpusRequestFitScore.DIRECT,
            reason_codes=[
                CorpusRelevanceReasonCode.ADJACENT_CONCERN_MATCH,
                CorpusRelevanceReasonCode.SYMPTOM_STATE_MATCH,
                CorpusRelevanceReasonCode.REQUEST_DIRECTION_MATCH,
            ],
            relevance_grade=CorpusRelevanceGrade.RELEVANT,
            note="표면 카테고리는 다르지만 같은 피부 상태와 안정화 요청을 직접 다룬다.",
        )

        assert judgment.relevance_grade is CorpusRelevanceGrade.RELEVANT

    def test_keyword_or_category_only_match_is_adjacent(self) -> None:
        judgment = NiaCaseCorpusRelevanceJudgment(
            review_key="3333333333333333",
            concern_fit=CorpusConcernFitScore.ADJACENT,
            context_fit=CorpusContextFitScore.NONE,
            request_fit=CorpusRequestFitScore.NONE,
            reason_codes=[CorpusRelevanceReasonCode.INCIDENTAL_KEYWORD_ONLY],
            relevance_grade=CorpusRelevanceGrade.ADJACENT,
            note="같은 범주의 단어만 포함하고 현재 요청에는 직접 답하지 않는다.",
        )

        assert judgment.relevance_grade is CorpusRelevanceGrade.ADJACENT

    def test_explicit_request_conflict_forces_not_relevant(self) -> None:
        judgment = NiaCaseCorpusRelevanceJudgment(
            review_key="4444444444444444",
            concern_fit=CorpusConcernFitScore.DIRECT,
            context_fit=CorpusContextFitScore.STRONG,
            request_fit=CorpusRequestFitScore.DIRECT,
            direction_conflicts=[
                CorpusDirectionConflictCode.EXPLICIT_REQUEST_CONFLICT
            ],
            reason_codes=[CorpusRelevanceReasonCode.EXPLICIT_DIRECTION_CONFLICT],
            relevance_grade=CorpusRelevanceGrade.NOT_RELEVANT,
            note="사용자가 요청한 현재 관리 방향과 Case 답변의 주된 방향이 반대다.",
        )

        assert judgment.relevance_grade is CorpusRelevanceGrade.NOT_RELEVANT

    def test_age_and_gender_are_not_hard_score_dimensions(self) -> None:
        judgment = NiaCaseCorpusRelevanceJudgment(
            review_key="5555555555555555",
            concern_fit=CorpusConcernFitScore.DIRECT,
            context_fit=CorpusContextFitScore.PARTIAL,
            request_fit=CorpusRequestFitScore.DIRECT,
            reason_codes=[CorpusRelevanceReasonCode.DEMOGRAPHIC_SUPPORT],
            relevance_grade=CorpusRelevanceGrade.HIGHLY_RELEVANT,
            note="나이와 성별은 보조 맥락이며 핵심 고민과 요청 방향이 관련도를 결정한다.",
        )

        assert "age" not in type(judgment).model_fields
        assert "gender" not in type(judgment).model_fields

    def test_rejects_grade_that_does_not_match_dimensions(self) -> None:
        with pytest.raises(ValidationError, match="최종 등급이 일치하지 않습니다"):
            NiaCaseCorpusRelevanceJudgment(
                review_key="6666666666666666",
                concern_fit=CorpusConcernFitScore.DIRECT,
                context_fit=CorpusContextFitScore.STRONG,
                request_fit=CorpusRequestFitScore.DIRECT,
                reason_codes=[CorpusRelevanceReasonCode.PRIMARY_CONCERN_MATCH],
                relevance_grade=CorpusRelevanceGrade.ADJACENT,
                note="세부 점수와 의도적으로 맞지 않는 등급이다.",
            )


class TestNiaCaseCorpusRelevanceReviewBuilder:
    ANCHOR_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_anchor_blind_v1.jsonl"
    )
    RERANK_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_rerank_unjudged_blind_v1.jsonl"
    )
    FINAL_GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_golden_v1.jsonl"
    )

    def test_merges_all_681_candidates_without_exposing_old_labels(self) -> None:
        loader = CandidatePoolArtifactLoader()
        items = NiaCaseCorpusRelevanceReviewBuilder().build(
            anchor_items=loader.load_blind(self.ANCHOR_BLIND_PATH),
            rerank_items=loader.load_blind(self.RERANK_BLIND_PATH),
        )
        old_golden = NiaCaseSemanticGoldenArtifact().load(self.FINAL_GOLDEN_PATH)

        assert len(items) == 40
        assert sum(item.candidate_count for item in items) == 681
        assert {
            candidate.review_key
            for item in items
            for candidate in item.candidates
        } == {
            qrel.review_key
            for item in old_golden.items
            for qrel in item.graded_qrels
        }
        for item in items:
            assert len({candidate.review_key for candidate in item.candidates}) == len(
                item.candidates
            )
            for candidate in item.candidates:
                dumped = candidate.model_dump(mode="json")
                assert "case_id" not in dumped
                assert "dense_rank" not in dumped
                assert "relevance_grade" not in dumped


class TestNiaCaseCorpusRelevanceJudgmentArtifacts:
    REVIEW_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relevance_review_blind_v1.jsonl"
    )
    JUDGMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relevance_judgments_acne_02_v1.jsonl"
    )

    def test_acne_02_judgments_cover_the_entire_blind_batch(self) -> None:
        batch = NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(
            self.JUDGMENT_PATH.read_text(encoding="utf-8")
        )
        review_item = next(
            item
            for item in CandidatePoolArtifactLoader().load_blind(self.REVIEW_PATH)
            if item.evaluation_id == batch.evaluation_id
        )

        assert batch.policy.value == "nia_corpus_relative_pooled_v1"
        assert len(batch.judgments) == review_item.candidate_count == 18
        assert {item.review_key for item in batch.judgments} == {
            item.review_key for item in review_item.candidates
        }


class TestNiaCaseCorpusRelativeGoldenSelection:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_blind_v1.jsonl"
    )

    def test_selects_twenty_four_queries_without_calibration_query(self) -> None:
        queries = NiaCaseCorpusRelativeQuerySelector().select(
            NiaCaseSemanticEvaluationQueryLoader().load(self.QUERY_PATH).items
        )

        assert len(queries) == 24
        assert sum(item.cohort is SemanticEvaluationCohort.CORE for item in queries) == 18
        assert (
            sum(item.cohort is SemanticEvaluationCohort.RARE_STRESS for item in queries)
            == 6
        )
        assert "evaluation_core_acne_02" not in {
            item.evaluation_id for item in queries
        }
        assert {item.evaluation_id for item in queries} == {
            item.value for item in CorpusRelativeEvaluationId
        }

    def test_samples_six_blind_candidates_per_active_query(self) -> None:
        queries = NiaCaseCorpusRelativeQuerySelector().select(
            NiaCaseSemanticEvaluationQueryLoader().load(self.QUERY_PATH).items
        )
        query_ids = {item.evaluation_id for item in queries}
        loader = CandidatePoolArtifactLoader()
        manifests, samples = NiaCaseCorpusRelativeAnchorSampler().sample(
            queries=queries,
            internal_items=[
                item
                for item in loader.load_internal(self.INTERNAL_POOL_PATH)
                if item.evaluation_id in query_ids
            ],
            blind_items=[
                item
                for item in loader.load_blind(self.BLIND_POOL_PATH)
                if item.evaluation_id in query_ids
            ],
        )

        assert len(manifests) == len(samples) == 24
        assert sum(item.candidate_count for item in samples) == 144
        for manifest, sample in zip(manifests, samples, strict=True):
            assert len(manifest.entries) == sample.candidate_count == 6
            assert (
                sum(
                    item.stratum is CorpusRelativeAnchorStratum.DENSE_TOP_40
                    for item in manifest.entries
                )
                == 3
            )
            assert (
                sum(
                    item.stratum is CorpusRelativeAnchorStratum.OFF_RANK_QUERY_MATCH
                    for item in manifest.entries
                )
                == 3
            )
            assert len({item.review_key for item in sample.candidates}) == 6


class TestNiaCaseCorpusRelativeAuditSampler:
    BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_anchor_blind_v1.jsonl"
    )
    AUDIT_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_audit_blind_v1.jsonl"
    )
    AUDIT_JUDGMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_audit_judgments_v1.jsonl"
    )
    GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v2.jsonl"
    )

    def test_samples_one_blind_candidate_per_active_query(self) -> None:
        result = NiaCaseCorpusRelativeAuditSampler().sample(
            CandidatePoolArtifactLoader().load_blind(self.BLIND_POOL_PATH)
        )

        assert len(result.manifests) == len(result.blind_items) == 24
        assert sum(item.candidate_count for item in result.blind_items) == 24
        assert all(
            item.policy is CorpusRelativeAuditSamplingPolicy.ONE_PER_QUERY_HASH_V1
            for item in result.manifests
        )
        for manifest, blind_item in zip(
            result.manifests,
            result.blind_items,
            strict=True,
        ):
            assert manifest.evaluation_id == blind_item.evaluation_id
            assert manifest.review_key == blind_item.candidates[0].review_key
            dumped = blind_item.model_dump(mode="json")
            assert "case_id" not in str(dumped)
            assert "dense_rank" not in str(dumped)
            assert "relevance_grade" not in str(dumped)

    def test_audit_artifacts_cover_sample_and_produce_expected_agreement(self) -> None:
        blind_items = CandidatePoolArtifactLoader().load_blind(self.AUDIT_BLIND_PATH)
        batches = [
            NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
            for line in self.AUDIT_JUDGMENT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        golden_cases = [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in self.GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        report = NiaCaseCorpusRelativeAuditEvaluator().evaluate(
            blind_items=blind_items,
            audit_batches=batches,
            golden_cases=golden_cases,
        )

        assert report.sample_count == 24
        assert report.exact_grade_agreement == pytest.approx(0.625)
        assert report.within_one_grade_agreement == pytest.approx(23 / 24)
        assert report.binary_relevance_agreement == pytest.approx(0.875)
        assert len(report.disagreements) == 9


class TestNiaCaseCorpusRelativeGoldenAdjudicator:
    GOLDEN_V2_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v2.jsonl"
    )
    GOLDEN_V3_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v3.jsonl"
    )
    AUDIT_JUDGMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_audit_judgments_v1.jsonl"
    )
    ADJUDICATION_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_adjudications_v1.jsonl"
    )

    def test_applies_only_five_recorded_changes_and_reproduces_v3(self) -> None:
        frozen_cases = self._load_golden(self.GOLDEN_V2_PATH)
        persisted_v3 = self._load_golden(self.GOLDEN_V3_PATH)
        audit_batches = [
            NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
            for line in self.AUDIT_JUDGMENT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        adjudications = [
            NiaCaseCorpusRelativeAdjudication.model_validate_json(line)
            for line in self.ADJUDICATION_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

        result = NiaCaseCorpusRelativeGoldenAdjudicator().apply(
            frozen_cases=frozen_cases,
            audit_batches=audit_batches,
            adjudications=adjudications,
        )

        assert result.reviewed_count == 9
        assert result.changed_count == 5
        assert result.golden_cases == persisted_v3
        assert len(result.golden_cases) == 24
        assert sum(item.total_qrel_count for item in result.golden_cases) == 200

    def _load_golden(self, path: Path) -> list[NiaCaseCorpusRelativeGoldenCase]:
        return [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class TestNiaCaseCorpusRelativeLiveMarkdownReporter:
    def test_does_not_report_metrics_when_top3_contains_unjudged_case(self) -> None:
        summary = NiaCaseCorpusRelativeLiveRunSummary(
            run_id="test_live_run",
            golden_version="v3",
            status=CorpusRelativeLiveEvaluationStatus.NEEDS_JUDGMENT,
            query_count=24,
            corpus_case_count=3581,
            dense_model="BAAI/bge-m3",
            reranker_model="BAAI/bge-reranker-v2-m3",
            candidate_count=100,
            top3_count=72,
            unjudged_count=1,
        )

        report = NiaCaseCorpusRelativeLiveMarkdownReporter().render(
            summary,
            baseline=None,
            live=None,
        )

        assert "판정 보류" in report
        assert "기준선 대비 결과" not in report


class TestNiaCaseCorpusRelativeLiveGoldenExpander:
    GOLDEN_V3_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v3.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )
    LIVE_UNJUDGED_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_unjudged_20260926_1416_v1.jsonl"
    )
    SUPPLEMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_supplement_judgments_20260926_1416_v1.jsonl"
    )

    def test_expands_v3_with_all_twenty_live_top3_judgments(self) -> None:
        golden_cases = [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in self.GOLDEN_V3_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        batches = [
            NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
            for line in self.SUPPLEMENT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

        result = NiaCaseCorpusRelativeLiveGoldenExpander().expand(
            golden_cases=golden_cases,
            internal_items=CandidatePoolArtifactLoader().load_internal(
                self.LIVE_POOL_PATH
            ),
            unjudged_items=CandidatePoolArtifactLoader().load_blind(
                self.LIVE_UNJUDGED_PATH
            ),
            supplement_batches=batches,
        )

        assert result.added_qrel_count == 20
        assert len(result.golden_cases) == 24
        assert sum(item.total_qrel_count for item in result.golden_cases) == 220
        assert all(item.anchor_qrel_count == 6 for item in result.golden_cases)


class TestNiaCaseRerankerRepeatChecker:
    BASELINE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )
    FIRST_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_probe_20260926_1416_v1.jsonl"
    )
    REPEAT_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_probe_repeat_20260926_1416_v1.jsonl"
    )

    def test_current_reranker_repeats_all_twenty_four_ordered_top3(self) -> None:
        first_items = self._load_probe(self.FIRST_PROBE_PATH)
        repeat_items = self._load_probe(self.REPEAT_PROBE_PATH)

        summary = NiaCaseRerankerRepeatChecker().compare(
            run_id="test_repeat",
            first_items=first_items,
            repeat_items=repeat_items,
            unjudged_count=0,
        )

        assert summary.query_count == 24
        assert summary.ordered_top3_match_count == 24
        assert summary.membership_top3_match_count == 24
        assert summary.unjudged_count == 0

    def test_live_dense_top40_matches_cached_baseline_for_all_queries(self) -> None:
        loader = CandidatePoolArtifactLoader()
        live_items = loader.load_internal(self.LIVE_POOL_PATH)
        live_ids = {item.evaluation_id for item in live_items}
        baseline_items = [
            item
            for item in loader.load_internal(self.BASELINE_POOL_PATH)
            if item.evaluation_id in live_ids
        ]

        summary = NiaCaseDenseBaselineChecker().compare(
            baseline_items,
            live_items,
        )

        assert summary.query_count == 24
        assert summary.ordered_top40_match_count == 24
        assert summary.membership_top40_match_count == 24

    def _load_probe(
        self,
        path: Path,
    ) -> list[NiaCaseCorpusRelativeLiveProbeItem]:
        return [
            NiaCaseCorpusRelativeLiveProbeItem.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class TestNiaCaseCorpusRelativeJudgmentArtifacts:
    REVIEW_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_anchor_blind_v1.jsonl"
    )
    JUDGMENT_DIRECTORY: ClassVar[Path] = Path("tests/agent/nia_case_eval_data")
    JUDGMENT_GLOB: ClassVar[str] = "nia_case_corpus_relative_judgments_*_v1.jsonl"
    RERANK_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_rerank_unjudged_blind_v1.jsonl"
    )
    RERANK_JUDGMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_rerank_judgments_v1.jsonl"
    )

    def test_each_active_judgment_batch_covers_one_blind_query(self) -> None:
        paths = sorted(self.JUDGMENT_DIRECTORY.glob(self.JUDGMENT_GLOB))
        batches = [
            NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            for path in paths
        ]
        blind_by_id = {
            item.evaluation_id: item
            for item in CandidatePoolArtifactLoader().load_blind(self.REVIEW_PATH)
        }

        assert len(batches) == 24
        assert sum(len(item.judgments) for item in batches) == 144
        assert len({item.evaluation_id for item in batches}) == len(batches)
        for batch in batches:
            assert batch.evaluation_id in blind_by_id
            assert {item.review_key for item in batch.judgments} == {
                item.review_key for item in blind_by_id[batch.evaluation_id].candidates
            }

    def test_rerank_judgments_cover_all_blind_supplements(self) -> None:
        batches = [
            NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
            for line in self.RERANK_JUDGMENT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        blind_by_id = {
            item.evaluation_id: item
            for item in CandidatePoolArtifactLoader().load_blind(
                self.RERANK_BLIND_PATH
            )
        }

        assert len(batches) == len(blind_by_id) == 24
        assert sum(len(item.judgments) for item in batches) == 56
        for batch in batches:
            assert {item.review_key for item in batch.judgments} == {
                item.review_key for item in blind_by_id[batch.evaluation_id].candidates
            }
