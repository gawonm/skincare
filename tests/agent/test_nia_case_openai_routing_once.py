from pathlib import Path

from agent.ports import LlmClient
from agent.rag.retrieval.case_candidate_selector import NiaCaseConcernCategory
from agent.rag.schemas import ProductTaxonomy
from agent.schemas import (
    Intent,
    IntentQueryPlan,
    ParsedRequest,
    RagRoute,
    UnderstandingRequest,
)
from tests.agent.evaluate_nia_case_openai_routing_once import (
    NiaCaseOpenAiQueryRelation,
    NiaCaseOpenAiRoutingRunner,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    SemanticEvaluationCohort,
)
from tests.agent.nia_case_semantic_golden_schemas import SemanticQueryType


class RecordingLlmClient(LlmClient):
    def __init__(self) -> None:
        self.requests: list[UnderstandingRequest] = []

    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        self.requests.append(request)
        return ParsedRequest(
            intents=[Intent.PRODUCT_DISCOVERY],
            query=request.message,
            query_plan=IntentQueryPlan(case_query="LLM 초안"),
            skin_concerns=["모공"],
            rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
        )


class TestNiaCaseOpenAiRoutingRunner:
    async def test_체크포인트에_저장된_질의는_API를_다시_호출하지_않는다(
        self,
        tmp_path: Path,
    ) -> None:
        client = RecordingLlmClient()
        runner = NiaCaseOpenAiRoutingRunner(
            llm=client,
            model="gpt-4o-mini",
            configured_max_retries=1,
        )
        runner.EXPECTED_QUERY_COUNT = 2
        queries = [
            self._query("evaluation_core_pores_01", "첫 번째 질의"),
            self._query("evaluation_core_pores_02", "두 번째 질의"),
        ]
        output_path = tmp_path / "checkpoint.jsonl"
        taxonomy = ProductTaxonomy(version="test-v1")

        first = await runner.run(queries, taxonomy, output_path)
        second = await runner.run(queries, taxonomy, output_path)

        assert len(client.requests) == 2
        assert first == second
        assert all(
            item.case_query_relation is NiaCaseOpenAiQueryRelation.EXACT
            for item in second
        )
        assert all(item.effective_max_retries == 0 for item in second)

    def _query(
        self,
        evaluation_id: str,
        query: str,
    ) -> NiaCaseSemanticEvaluationQuery:
        return NiaCaseSemanticEvaluationQuery(
            evaluation_id=evaluation_id,
            cohort=SemanticEvaluationCohort.CORE,
            query_type=SemanticQueryType.SIMPLE,
            query=query,
            primary_concerns=[NiaCaseConcernCategory.PORES],
            calibration_template_ids=["calibration_pores_oily_01"],
        )
