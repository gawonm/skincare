"""실제 NIA Case DB에서 단일 질의와 복수 질의 검색 품질을 비교한다.

실행 예:
    uv run python -m tests.agent.case_retrieval_recall_eval --golden <검토된 JSONL 경로>
"""

import argparse
import asyncio
import math
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import Field, ValidationError, model_validator

from agent.query_planning import IntentQueryPlanner
from agent.rag.case_schemas import (
    CaseRerankRequest,
    CaseSearchHit,
    CaseSearchRequest,
    CaseSearchResult,
)
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.ports import CaseReranker, CaseRetriever, TextEmbedder
from agent.rag.retrieval.case_reranker import LocalBgeCaseRerankerV2M3
from agent.rag.retrieval.case_result_fusion import (
    CaseSearchContribution,
    CaseSearchFusionRequest,
    CaseSearchResultFusion,
)
from agent.rag.retrieval.cross_encoder import LocalBgeCrossEncoderScorer
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingRequest,
    LocalEmbeddingModel,
    LookupStatus,
    RagModel,
)
from agent.schemas import (
    Intent,
    IntentQueryPlan,
    ParsedRequest,
    QueryPlanningRequest,
    RagRoute,
)
from backend.services.two_layer_rag_adapters import BackendNiaCaseRetriever
from core.database import Database
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    TwoLayerAgentModelConfigFactory,
    Utf8ConsoleConfigurator,
)


class CaseRetrievalExperiment(StrEnum):
    BASELINE = "baseline"
    MULTI_QUERY = "multi_query"
    MULTI_QUERY_RERANK = "multi_query_rerank"


class CaseRetrievalGoldenItem(RagModel):
    evaluation_id: str = Field(min_length=1)
    original_message: str = Field(min_length=1)
    canonical_case_query: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)
    relevant_case_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relevant_case_ids(self) -> Self:
        if len(self.relevant_case_ids) != len(set(self.relevant_case_ids)):
            raise ValueError("골든셋 relevant_case_ids가 중복되었습니다.")
        return self


class CaseRetrievalGoldenSet(RagModel):
    items: list[CaseRetrievalGoldenItem] = Field(min_length=1)


class CaseRetrievalEvaluationArguments(RagModel):
    golden_path: Path


class CaseRetrievalMetricRequest(RagModel):
    retrieved_case_ids: list[str]
    final_case_ids: list[str]
    relevant_case_ids: list[str] = Field(min_length=1)


class CaseRetrievalMetrics(RagModel):
    hit_at_20: bool
    recall_at_20: float = Field(ge=0.0, le=1.0)
    mrr_at_3: float = Field(ge=0.0, le=1.0)
    ndcg_at_3: float = Field(ge=0.0, le=1.0)


class CaseRetrievalRanking(RagModel):
    experiment: CaseRetrievalExperiment
    retrieved_case_ids: list[str]
    final_case_ids: list[str]
    metrics: CaseRetrievalMetrics


class CaseRetrievalEvaluationResult(RagModel):
    evaluation_id: str = Field(min_length=1)
    query_plan: IntentQueryPlan
    relevant_case_ids: list[str] = Field(min_length=1)
    rankings: list[CaseRetrievalRanking] = Field(min_length=3, max_length=3)


class CaseRetrievalExperimentSummary(RagModel):
    experiment: CaseRetrievalExperiment
    query_count: int = Field(ge=1)
    hit_at_20: float = Field(ge=0.0, le=1.0)
    recall_at_20: float = Field(ge=0.0, le=1.0)
    mrr_at_3: float = Field(ge=0.0, le=1.0)
    ndcg_at_3: float = Field(ge=0.0, le=1.0)


class CaseRetrievalEvaluationSummary(RagModel):
    experiments: list[CaseRetrievalExperimentSummary] = Field(min_length=3, max_length=3)


class CaseRetrievalEvaluationArgumentParser:
    def parse(self) -> CaseRetrievalEvaluationArguments:
        parser = argparse.ArgumentParser(
            description="검토된 NIA Case 골든셋으로 Recall@20과 Top-3 품질을 비교합니다."
        )
        parser.add_argument(
            "--golden",
            required=True,
            type=Path,
            help="evaluation_id, original_message, canonical_case_query, skin_concerns, relevant_case_ids JSONL",
        )
        arguments = parser.parse_args()
        return CaseRetrievalEvaluationArguments(golden_path=arguments.golden)


class CaseRetrievalGoldenSetLoader:
    def load(self, arguments: CaseRetrievalEvaluationArguments) -> CaseRetrievalGoldenSet:
        items: list[CaseRetrievalGoldenItem] = []
        try:
            with arguments.golden_path.open("r", encoding="utf-8") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    try:
                        items.append(CaseRetrievalGoldenItem.model_validate_json(line))
                    except ValidationError as error:
                        raise RuntimeError(
                            "NIA Case 골든셋 스키마가 잘못되었습니다: "
                            f"path={arguments.golden_path}, line={line_number}, detail={error}"
                        ) from error
        except OSError as error:
            raise RuntimeError(
                f"NIA Case 골든셋을 읽지 못했습니다: {arguments.golden_path}: {error}"
            ) from error
        return CaseRetrievalGoldenSet(items=items)


class CaseRetrievalMetricCalculator:
    RETRIEVAL_CUTOFF: ClassVar[int] = 20
    FINAL_CUTOFF: ClassVar[int] = 3

    def calculate(self, request: CaseRetrievalMetricRequest) -> CaseRetrievalMetrics:
        relevant = set(request.relevant_case_ids)
        retrieved = request.retrieved_case_ids[: self.RETRIEVAL_CUTOFF]
        final = request.final_case_ids[: self.FINAL_CUTOFF]
        matched = relevant.intersection(retrieved)
        reciprocal_rank = next(
            (
                1.0 / rank
                for rank, case_id in enumerate(final, start=1)
                if case_id in relevant
            ),
            0.0,
        )
        dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank, case_id in enumerate(final, start=1)
            if case_id in relevant
        )
        ideal_count = min(len(relevant), self.FINAL_CUTOFF)
        ideal_dcg = sum(
            1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1)
        )
        return CaseRetrievalMetrics(
            hit_at_20=bool(matched),
            recall_at_20=len(matched) / len(relevant),
            mrr_at_3=reciprocal_rank,
            ndcg_at_3=dcg / ideal_dcg,
        )


class CaseRetrievalEvaluator:
    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"

    def __init__(
        self,
        embedder: TextEmbedder,
        retriever: CaseRetriever,
        reranker: CaseReranker,
    ) -> None:
        self._embedder = embedder
        self._retriever = retriever
        self._reranker = reranker
        self._planner = IntentQueryPlanner()
        self._fusion = CaseSearchResultFusion()
        self._metrics = CaseRetrievalMetricCalculator()

    async def evaluate(
        self,
        golden: CaseRetrievalGoldenItem,
    ) -> CaseRetrievalEvaluationResult:
        query_plan = self._planner.build(
            QueryPlanningRequest(
                original_message=golden.original_message,
                parsed_request=ParsedRequest(
                    intents=[Intent.PRODUCT_DISCOVERY],
                    query=golden.original_message,
                    query_plan=IntentQueryPlan(
                        case_query=golden.canonical_case_query
                    ),
                    skin_concerns=golden.skin_concerns,
                    rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
                ),
            )
        )
        canonical_query = query_plan.case_query
        if canonical_query is None:
            raise RuntimeError(f"Case 질의가 생성되지 않았습니다: {golden.evaluation_id}")
        retrieval_queries = query_plan.case_retrieval_queries
        if not retrieval_queries:
            raise RuntimeError(f"복수 검색 질의가 생성되지 않았습니다: {golden.evaluation_id}")

        texts = list(
            dict.fromkeys(
                [canonical_query, *[query.text for query in retrieval_queries]]
            )
        )
        embedding = await self._embedder.embed(EmbeddingRequest(texts=texts))
        if embedding.model != LocalEmbeddingModel.BGE_M3.value:
            raise RuntimeError(
                "NIA Case 평가 임베딩 모델이 BGE-M3가 아닙니다: "
                f"actual={embedding.model}"
            )
        if len(embedding.vectors) != len(texts):
            raise RuntimeError(
                "NIA Case 평가 질의와 임베딩 수가 다릅니다: "
                f"queries={len(texts)}, vectors={len(embedding.vectors)}"
            )
        if any(
            len(vector.values) != BGE_M3_EMBEDDING_DIMENSIONS
            for vector in embedding.vectors
        ):
            raise RuntimeError("NIA Case 평가 임베딩에 1,024차원이 아닌 벡터가 있습니다.")
        vectors_by_text = dict(zip(texts, embedding.vectors, strict=True))

        baseline = await self._search(
            CaseSearchRequest(
                query=canonical_query,
                query_embedding=vectors_by_text[canonical_query],
                text_version=self.TEXT_VERSION,
                embedding_model=embedding.model,
            )
        )
        contributions = [
            CaseSearchContribution(
                query=query.text,
                result=await self._search(
                    CaseSearchRequest(
                        query=query.text,
                        query_embedding=vectors_by_text[query.text],
                        text_version=self.TEXT_VERSION,
                        embedding_model=embedding.model,
                    )
                ),
            )
            for query in retrieval_queries
        ]
        fusion = self._fusion.fuse(
            CaseSearchFusionRequest(contributions=contributions)
        )
        if fusion.failures:
            details = "; ".join(
                f"{failure.query}: {failure.message}" for failure in fusion.failures
            )
            raise RuntimeError(f"NIA Case 복수 질의 평가 검색이 일부 실패했습니다: {details}")
        fused = fusion.search_result

        baseline_reranked = await self._rerank(canonical_query, baseline)
        multi_query_reranked = await self._rerank(canonical_query, fused)
        full_rerank_query = query_plan.case_rerank_query or canonical_query
        full_reranked = await self._rerank(full_rerank_query, fused)

        return CaseRetrievalEvaluationResult(
            evaluation_id=golden.evaluation_id,
            query_plan=query_plan,
            relevant_case_ids=golden.relevant_case_ids,
            rankings=[
                self._ranking(
                    CaseRetrievalExperiment.BASELINE,
                    baseline.hits,
                    baseline_reranked,
                    golden,
                ),
                self._ranking(
                    CaseRetrievalExperiment.MULTI_QUERY,
                    fused.hits,
                    multi_query_reranked,
                    golden,
                ),
                self._ranking(
                    CaseRetrievalExperiment.MULTI_QUERY_RERANK,
                    fused.hits,
                    full_reranked,
                    golden,
                ),
            ],
        )

    async def _search(self, request: CaseSearchRequest) -> CaseSearchResult:
        result = await self._retriever.search(request)
        if result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
            raise RuntimeError(
                "NIA Case 평가 검색 실패: "
                f"query={request.query}, status={result.status.value}, "
                f"detail={result.error_message or '원인 미상'}"
            )
        return result

    async def _rerank(
        self,
        query: str,
        search: CaseSearchResult,
    ) -> list[CaseSearchHit]:
        if search.status is not LookupStatus.SUCCESS:
            return []
        result = await self._reranker.rerank(
            CaseRerankRequest(query=query, candidates=search.hits)
        )
        return result.hits

    def _ranking(
        self,
        experiment: CaseRetrievalExperiment,
        retrieved: list[CaseSearchHit],
        final: list[CaseSearchHit],
        golden: CaseRetrievalGoldenItem,
    ) -> CaseRetrievalRanking:
        retrieved_case_ids = [hit.case_id for hit in retrieved]
        final_case_ids = [hit.case_id for hit in final]
        return CaseRetrievalRanking(
            experiment=experiment,
            retrieved_case_ids=retrieved_case_ids,
            final_case_ids=final_case_ids,
            metrics=self._metrics.calculate(
                CaseRetrievalMetricRequest(
                    retrieved_case_ids=retrieved_case_ids,
                    final_case_ids=final_case_ids,
                    relevant_case_ids=golden.relevant_case_ids,
                )
            ),
        )


class CaseRetrievalEvaluationReporter:
    def summarize(
        self,
        results: list[CaseRetrievalEvaluationResult],
    ) -> CaseRetrievalEvaluationSummary:
        summaries: list[CaseRetrievalExperimentSummary] = []
        for experiment in CaseRetrievalExperiment:
            metrics = [
                ranking.metrics
                for result in results
                for ranking in result.rankings
                if ranking.experiment is experiment
            ]
            if not metrics:
                raise RuntimeError(f"평가 결과에 실험이 없습니다: {experiment.value}")
            count = len(metrics)
            summaries.append(
                CaseRetrievalExperimentSummary(
                    experiment=experiment,
                    query_count=count,
                    hit_at_20=sum(float(metric.hit_at_20) for metric in metrics) / count,
                    recall_at_20=sum(metric.recall_at_20 for metric in metrics) / count,
                    mrr_at_3=sum(metric.mrr_at_3 for metric in metrics) / count,
                    ndcg_at_3=sum(metric.ndcg_at_3 for metric in metrics) / count,
                )
            )
        return CaseRetrievalEvaluationSummary(experiments=summaries)

    def print(
        self,
        results: list[CaseRetrievalEvaluationResult],
    ) -> None:
        for result in results:
            print(result.model_dump_json(indent=2))
        print(self.summarize(results).model_dump_json(indent=2))


class CaseRetrievalEvaluationCli:
    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        arguments = CaseRetrievalEvaluationArgumentParser().parse()
        golden_set = CaseRetrievalGoldenSetLoader().load(arguments)
        database: Database = ConfiguredDatabaseFactory().create()
        try:
            config = TwoLayerAgentModelConfigFactory()
            embedding_config = config.create_embedding()
            reranker_config = config.create_reranker()
            scorer = LocalBgeCrossEncoderScorer(reranker_config)
            evaluator = CaseRetrievalEvaluator(
                embedder=TextEmbedderFactory().create(embedding_config),
                retriever=BackendNiaCaseRetriever(database.session_factory),
                reranker=LocalBgeCaseRerankerV2M3(
                    reranker_config,
                    scorer=scorer,
                ),
            )
            results = [
                await evaluator.evaluate(golden) for golden in golden_set.items
            ]
            CaseRetrievalEvaluationReporter().print(results)
        finally:
            await database.dispose()


if __name__ == "__main__":
    asyncio.run(CaseRetrievalEvaluationCli.main())
