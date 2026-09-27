from pathlib import Path

import pytest

from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeQueryEvaluation,
)
from tests.agent.evaluate_nia_case_openai_e2e import NiaCaseOpenAiE2ESlice
from tests.agent.evaluate_nia_case_openai_route_update import (
    NiaCaseOpenAiRouteReplayer,
    NiaCaseRouteUpdateOutcome,
)
from tests.agent.evaluate_nia_case_openai_routing_once import (
    NiaCaseOpenAiRoutingCheckpoint,
)


class TestNiaCaseOpenAiRouteUpdate:
    ROUTING_PATH = Path(
        "tests/agent/nia_case_eval_data/nia_case_openai_routing_once_20260926_1740_v1.jsonl"
    )
    RETRIEVAL_PATH = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_results_20260926_1416_v1.jsonl"
    )

    def test_저장된_24건에서_두_경로를_복구하고_회귀를_만들지_않는다(self) -> None:
        report = NiaCaseOpenAiRouteReplayer().replay(
            "test-route-update",
            NiaCaseOpenAiRoutingCheckpoint().load(self.ROUTING_PATH),
            self._retrieval_results(),
        )
        outcomes = {item.evaluation_id: item.outcome for item in report.items}
        conditional = next(
            item
            for item in report.updated_e2e.metrics
            if item.slice is NiaCaseOpenAiE2ESlice.ROUTED_CONDITIONAL
        )

        assert report.query_count == 24
        assert report.updated_case_route_count == 23
        assert report.corrected_count == 2
        assert report.intentional_bypass_count == 1
        assert report.regressed_count == 0
        assert report.exact_case_query_count == 24
        assert outcomes["evaluation_core_acne_04"] is NiaCaseRouteUpdateOutcome.CORRECTED
        assert outcomes["evaluation_rare_sagging_01"] is NiaCaseRouteUpdateOutcome.CORRECTED
        assert (
            outcomes["evaluation_rare_wrinkles_02"]
            is NiaCaseRouteUpdateOutcome.INTENTIONAL_BYPASS
        )
        assert conditional.case_route_rate == 1.0
        assert conditional.precision_at_3 == pytest.approx(0.7681159420)

    def _retrieval_results(self) -> list[NiaCaseCorpusRelativeQueryEvaluation]:
        return [
            NiaCaseCorpusRelativeQueryEvaluation.model_validate_json(line)
            for line in self.RETRIEVAL_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
