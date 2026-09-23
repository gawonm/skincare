import math

import pytest

from tests.agent.case_retrieval_recall_eval import (
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
        assert metrics.mrr_at_3 == 0.5
        assert metrics.ndcg_at_3 == pytest.approx(actual_dcg / ideal_dcg)

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
        assert metrics.mrr_at_3 == 0.0
        assert metrics.ndcg_at_3 == 0.0
