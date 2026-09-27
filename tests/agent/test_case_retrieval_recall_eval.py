import math
from pathlib import Path
from typing import ClassVar

import pytest

from tests.agent.case_retrieval_recall_eval import (
    CaseRetrievalEvaluationArguments,
    CaseRetrievalGoldenSetLoader,
    CaseRetrievalMetricCalculator,
    CaseRetrievalMetricRequest,
)


class TestCaseRetrievalMetricCalculator:
    def test_검색_Recall과_최종_Top3_순위를_분리해_계산한다(self) -> None:
        metrics = CaseRetrievalMetricCalculator().calculate(
            CaseRetrievalMetricRequest(
                retrieved_case_ids=["other", "relevant-a", "relevant-b"],
                final_case_ids=["other", "relevant-b", "relevant-a"],
                relevant_case_ids=["relevant-a", "relevant-b"],
            )
        )

        ideal_dcg = 1.0 + 1.0 / math.log2(3)
        actual_dcg = 1.0 / math.log2(3) + 1.0 / math.log2(4)
        assert metrics.hit_at_20 is True
        assert metrics.recall_at_20 == 1.0
        assert metrics.hit_at_40 is True
        assert metrics.recall_at_40 == 1.0
        assert metrics.mrr_at_3 == 0.5
        assert metrics.ndcg_at_3 == pytest.approx(actual_dcg / ideal_dcg)

    def test_Top20_밖_Top40_안의_Case를_확장_회수로_구분한다(self) -> None:
        retrieved = [f"other-{rank}" for rank in range(1, 30)]
        retrieved.append("relevant")

        metrics = CaseRetrievalMetricCalculator().calculate(
            CaseRetrievalMetricRequest(
                retrieved_case_ids=retrieved,
                final_case_ids=[],
                relevant_case_ids=["relevant"],
            )
        )

        assert metrics.hit_at_20 is False
        assert metrics.recall_at_20 == 0.0
        assert metrics.hit_at_40 is True
        assert metrics.recall_at_40 == 1.0

    def test_관련_Case가_없으면_모든_지표가_0이다(self) -> None:
        metrics = CaseRetrievalMetricCalculator().calculate(
            CaseRetrievalMetricRequest(
                retrieved_case_ids=["other"],
                final_case_ids=["other"],
                relevant_case_ids=["relevant"],
            )
        )

        assert metrics.hit_at_20 is False
        assert metrics.recall_at_20 == 0.0
        assert metrics.hit_at_40 is False
        assert metrics.recall_at_40 == 0.0
        assert metrics.mrr_at_3 == 0.0
        assert metrics.ndcg_at_3 == 0.0


class TestCaseRetrievalGoldenSet:
    GOLDEN_PATH: ClassVar[Path] = Path("tests/agent/nia_case_eval_data/nia_case_retrieval_golden_24.jsonl")
    EXPECTED_TOTAL_COUNT: ClassVar[int] = 24
    EXPECTED_DEV_COUNT: ClassVar[int] = 18
    EXPECTED_HOLDOUT_COUNT: ClassVar[int] = 6

    def test_Anchor_Case_24건이_중복과_임시_ID_없이_고정되어_있다(self) -> None:
        golden_set = CaseRetrievalGoldenSetLoader().load(
            CaseRetrievalEvaluationArguments(golden_path=self.GOLDEN_PATH)
        )
        evaluation_ids = [item.evaluation_id for item in golden_set.items]
        relevant_case_ids = [
            case_id for item in golden_set.items for case_id in item.relevant_case_ids
        ]

        assert len(golden_set.items) == self.EXPECTED_TOTAL_COUNT
        assert len(evaluation_ids) == len(set(evaluation_ids))
        assert len(relevant_case_ids) == len(set(relevant_case_ids))
        assert all(len(item.relevant_case_ids) == 1 for item in golden_set.items)
        # 임시 ID가 남으면 모든 평가가 0점이 되어도 실행 자체는 성공하므로 명시적으로 막는다.
        assert all("__PENDING" not in case_id for case_id in relevant_case_ids)
        assert sum(item.evaluation_id.startswith("dev_") for item in golden_set.items) == (
            self.EXPECTED_DEV_COUNT
        )
        assert (
            sum(item.evaluation_id.startswith("holdout_") for item in golden_set.items)
            == self.EXPECTED_HOLDOUT_COUNT
        )
