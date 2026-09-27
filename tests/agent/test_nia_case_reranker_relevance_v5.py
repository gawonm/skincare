from pathlib import Path
from typing import ClassVar, TypeVar

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeGoldenCase,
)
from tests.agent.finalize_nia_case_reranker_relevance_v5 import (
    NiaCaseRerankerRelevanceSummary,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
)

RerankerArtifactModel = TypeVar("RerankerArtifactModel", bound=RagModel)


class TestNiaCaseRerankerRelevanceV5:
    UNJUDGED_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_reranker_relevance_unjudged_20260926_2150_v1.jsonl"
    )
    SUPPLEMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_reranker_relevance_supplement_judgments_20260926_2150_v1.jsonl"
    )
    GOLDEN_V5_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v5.jsonl"
    )
    SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_reranker_relevance_final_summary_20260926_2150_v1.jsonl"
    )

    def test_추가_판정이_미판정_21건을_정확히_덮는다(self) -> None:
        unjudged = CandidatePoolArtifactLoader().load_blind(self.UNJUDGED_PATH)
        supplements = self._load_models(
            self.SUPPLEMENT_PATH,
            NiaCaseCorpusRelevanceJudgmentBatch,
        )

        expected = {
            (item.evaluation_id, candidate.review_key)
            for item in unjudged
            for candidate in item.candidates
        }
        actual = {
            (batch.evaluation_id, judgment.review_key)
            for batch in supplements
            for judgment in batch.judgments
        }

        assert len(expected) == 21
        assert actual == expected

    def test_골든_v5는_24질의와_241개_qrel을_중복_없이_보존한다(self) -> None:
        golden_cases = self._load_models(
            self.GOLDEN_V5_PATH,
            NiaCaseCorpusRelativeGoldenCase,
        )

        assert len(golden_cases) == 24
        assert sum(item.total_qrel_count for item in golden_cases) == 241
        for golden in golden_cases:
            review_keys = [item.review_key for item in golden.graded_qrels]
            case_ids = [item.case_id for item in golden.graded_qrels]
            assert len(review_keys) == len(set(review_keys))
            assert len(case_ids) == len(set(case_ids))

    def test_Case_route_23의_관련성_지표가_확정값과_일치한다(self) -> None:
        summary = self._load_models(
            self.SUMMARY_PATH,
            NiaCaseRerankerRelevanceSummary,
        )[0]

        assert summary.added_qrel_count == 21
        assert summary.candidate_count_min == 40
        assert summary.candidate_count_max == 40
        assert summary.after_case_route.hit_rate_at_3 == 21 / 23
        assert summary.after_case_route.precision_at_3 == 54 / 69
        assert summary.membership_changed_count == 17
        assert summary.hit_rate_gain_count == 1
        assert summary.hit_rate_loss_count == 0
        assert summary.after_case_route.exact_duplicate_total == 0

    def _load_models(
        self,
        path: Path,
        model_type: type[RerankerArtifactModel],
    ) -> list[RerankerArtifactModel]:
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
