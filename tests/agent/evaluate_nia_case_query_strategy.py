"""NIA Case의 요약 질의와 문맥 보존 질의를 동일한 Dense 조건에서 비교한다."""

import asyncio
import re
from enum import StrEnum
from math import log2
from pathlib import Path
from statistics import fmean
from typing import ClassVar

from pydantic import Field, FiniteFloat

from agent.rag.case_schemas import (
    DEFAULT_CASE_CANDIDATE_LIMIT,
    CaseSearchRequest,
)
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.ports import CaseRetriever, TextEmbedder
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingRequest,
    LookupStatus,
    RagModel,
)
from backend.services.two_layer_rag_adapters import BackendNiaCaseRetriever
from core.database import Database
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    CorpusRelativeEvaluationSlice,
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeGoldenCase,
)
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    TwoLayerAgentModelConfigFactory,
    Utf8ConsoleConfigurator,
)
from tests.agent.nia_case_semantic_candidate_pool import CandidatePoolJsonlWriter
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
    SemanticEvaluationCohort,
)


class NiaCaseQueryStrategy(StrEnum):
    CONCERN_SUMMARY = "concern_summary"
    PROFILE_SUMMARY = "profile_summary"
    CONTEXT_PRESERVED = "context_preserved"


class NiaCaseQueryStrategyOutcome(StrEnum):
    PROFILE_SUMMARY_WINS = "profile_summary_wins"
    CONTEXT_PRESERVED_WINS = "context_preserved_wins"
    TIE = "tie"


class NiaCaseProfileQueryContext(StrEnum):
    MALE = "남성"
    FEMALE = "여성"
    SPRING = "봄"
    SUMMER = "여름"
    AUTUMN = "가을"
    WINTER = "겨울"
    TRANSITION = "환절기"
    OILY = "지성"
    DRY = "건성"
    COMBINATION = "복합성"
    NORMAL = "중성"
    SENSITIVE = "민감성"


class NiaCaseQueryVariant(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    cohort: SemanticEvaluationCohort
    strategy: NiaCaseQueryStrategy
    query: str = Field(min_length=1)


class NiaCaseDenseQueryHit(RagModel):
    case_id: str = Field(min_length=1)
    rank: int = Field(ge=1, le=DEFAULT_CASE_CANDIDATE_LIMIT)
    similarity: FiniteFloat


class NiaCaseDenseQueryMetrics(RagModel):
    anchor_success_at_20: bool
    anchor_recall_at_20: float = Field(ge=0.0, le=1.0)
    anchor_success_at_40: bool
    anchor_recall_at_40: float = Field(ge=0.0, le=1.0)
    reciprocal_rank_at_40: float = Field(ge=0.0, le=1.0)
    ndcg_at_40: float = Field(ge=0.0, le=1.0)
    retrieved_relevant_anchor_ids: list[str]


class NiaCaseDenseQueryResult(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    cohort: SemanticEvaluationCohort
    strategy: NiaCaseQueryStrategy
    query: str = Field(min_length=1)
    relevant_anchor_ids: list[str]
    hits: list[NiaCaseDenseQueryHit] = Field(
        min_length=DEFAULT_CASE_CANDIDATE_LIMIT,
        max_length=DEFAULT_CASE_CANDIDATE_LIMIT,
    )
    metrics: NiaCaseDenseQueryMetrics


class NiaCaseDenseQueryAggregate(RagModel):
    strategy: NiaCaseQueryStrategy
    slice: CorpusRelativeEvaluationSlice
    query_count: int = Field(ge=1)
    anchor_success_at_20: float = Field(ge=0.0, le=1.0)
    anchor_recall_at_20: float = Field(ge=0.0, le=1.0)
    anchor_success_at_40: float = Field(ge=0.0, le=1.0)
    anchor_recall_at_40: float = Field(ge=0.0, le=1.0)
    mean_reciprocal_rank_at_40: float = Field(ge=0.0, le=1.0)
    mean_ndcg_at_40: float = Field(ge=0.0, le=1.0)


class NiaCaseDenseQueryPairwiseResult(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    outcome: NiaCaseQueryStrategyOutcome
    profile_summary_relevant_count: int = Field(ge=0)
    context_preserved_relevant_count: int = Field(ge=0)
    profile_summary_first_relevant_rank: int | None = Field(
        default=None,
        ge=1,
        le=DEFAULT_CASE_CANDIDATE_LIMIT,
    )
    context_preserved_first_relevant_rank: int | None = Field(
        default=None,
        ge=1,
        le=DEFAULT_CASE_CANDIDATE_LIMIT,
    )
    profile_summary_only_anchor_ids: list[str]
    context_preserved_only_anchor_ids: list[str]
    top40_overlap_count: int = Field(ge=0, le=DEFAULT_CASE_CANDIDATE_LIMIT)


class NiaCaseDenseQueryStrategyReport(RagModel):
    query_count: int = Field(ge=1)
    results: list[NiaCaseDenseQueryResult] = Field(min_length=1)
    aggregates: list[NiaCaseDenseQueryAggregate] = Field(min_length=1)
    pairwise: list[NiaCaseDenseQueryPairwiseResult] = Field(min_length=1)
    profile_summary_win_count: int = Field(ge=0)
    context_preserved_win_count: int = Field(ge=0)
    tie_count: int = Field(ge=0)


class NiaCaseQueryVariantBuilder:
    SUMMARY_PURPOSE: ClassVar[str] = "피부 관련 성분 및 주의사항"
    _AGE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<!\d)(?:[1-9]0대|\d{1,2}(?:세|살))"
    )
    _CONTEXT_ALIASES: ClassVar[
        dict[NiaCaseProfileQueryContext, tuple[str, ...]]
    ] = {
        NiaCaseProfileQueryContext.MALE: ("남성", "남자"),
        NiaCaseProfileQueryContext.FEMALE: ("여성", "여자"),
        NiaCaseProfileQueryContext.SPRING: ("봄",),
        NiaCaseProfileQueryContext.SUMMER: ("여름",),
        NiaCaseProfileQueryContext.AUTUMN: ("가을",),
        NiaCaseProfileQueryContext.WINTER: ("겨울",),
        NiaCaseProfileQueryContext.TRANSITION: ("환절기",),
        NiaCaseProfileQueryContext.OILY: ("지성",),
        NiaCaseProfileQueryContext.DRY: ("건성",),
        NiaCaseProfileQueryContext.COMBINATION: ("복합성",),
        NiaCaseProfileQueryContext.NORMAL: ("중성",),
        NiaCaseProfileQueryContext.SENSITIVE: ("민감성",),
    }

    def build(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
    ) -> list[NiaCaseQueryVariant]:
        variants: list[NiaCaseQueryVariant] = []
        for query in queries:
            concern_terms = list(
                dict.fromkeys(
                    concern.value
                    for concern in [
                        *query.primary_concerns,
                        *query.secondary_concerns,
                    ]
                )
            )
            concern_text = " ".join(concern_terms)
            profile_terms = self._deduplicate_terms(
                [*self._profile_context(query.query), *concern_terms]
            )
            variants.extend(
                [
                    NiaCaseQueryVariant(
                        evaluation_id=query.evaluation_id,
                        cohort=query.cohort,
                        strategy=NiaCaseQueryStrategy.CONCERN_SUMMARY,
                        query=f"{concern_text} {self.SUMMARY_PURPOSE}",
                    ),
                    NiaCaseQueryVariant(
                        evaluation_id=query.evaluation_id,
                        cohort=query.cohort,
                        strategy=NiaCaseQueryStrategy.PROFILE_SUMMARY,
                        query=" ".join([*profile_terms, self.SUMMARY_PURPOSE]),
                    ),
                    NiaCaseQueryVariant(
                        evaluation_id=query.evaluation_id,
                        cohort=query.cohort,
                        strategy=NiaCaseQueryStrategy.CONTEXT_PRESERVED,
                        query=query.query,
                    ),
                ]
            )
        return variants

    def _profile_context(self, query: str) -> list[str]:
        positioned: list[tuple[int, str]] = [
            (match.start(), match.group(0))
            for match in self._AGE_PATTERN.finditer(query)
        ]
        lowered = query.casefold()
        for context, aliases in self._CONTEXT_ALIASES.items():
            positions = [lowered.find(alias.casefold()) for alias in aliases]
            found = [position for position in positions if position >= 0]
            if found:
                positioned.append((min(found), context.value))
        positioned.sort(key=lambda item: item[0])
        return list(dict.fromkeys(value for _, value in positioned))

    def _deduplicate_terms(self, terms: list[str]) -> list[str]:
        result: list[str] = []
        for term in terms:
            normalized = term.casefold()
            if any(normalized in existing.casefold() for existing in result):
                continue
            # 짧은 프로필 표현보다 판정에 사용한 구체적인 고민명을 남겨 검색 의도를 보존한다.
            result = [
                existing
                for existing in result
                if existing.casefold() not in normalized
            ]
            result.append(term)
        return result


class NiaCaseDenseQueryMetricCalculator:
    TOP_20_CUTOFF: ClassVar[int] = 20

    def calculate(
        self,
        hits: list[NiaCaseDenseQueryHit],
        relevant_anchor_ids: list[str],
    ) -> NiaCaseDenseQueryMetrics:
        relevant = set(relevant_anchor_ids)
        top20_ids = [item.case_id for item in hits[: self.TOP_20_CUTOFF]]
        top40_ids = [item.case_id for item in hits]
        matched20 = relevant.intersection(top20_ids)
        matched40 = relevant.intersection(top40_ids)
        first_relevant_rank = next(
            (item.rank for item in hits if item.case_id in relevant),
            None,
        )
        gains = [1 if item.case_id in relevant else 0 for item in hits]
        ideal_relevant_count = min(len(relevant), DEFAULT_CASE_CANDIDATE_LIMIT)
        ideal_dcg = sum(
            1.0 / log2(rank + 1)
            for rank in range(1, ideal_relevant_count + 1)
        )
        dcg = sum(
            gain / log2(rank + 1)
            for rank, gain in enumerate(gains, start=1)
        )
        return NiaCaseDenseQueryMetrics(
            anchor_success_at_20=bool(matched20),
            anchor_recall_at_20=(
                len(matched20) / len(relevant) if relevant else 0.0
            ),
            anchor_success_at_40=bool(matched40),
            anchor_recall_at_40=(
                len(matched40) / len(relevant) if relevant else 0.0
            ),
            reciprocal_rank_at_40=(
                1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
            ),
            ndcg_at_40=dcg / ideal_dcg if ideal_dcg else 0.0,
            retrieved_relevant_anchor_ids=sorted(matched40),
        )


class NiaCaseDenseQueryStrategyEvaluator:
    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"

    def __init__(self, embedder: TextEmbedder, retriever: CaseRetriever) -> None:
        self._embedder = embedder
        self._retriever = retriever
        self._calculator = NiaCaseDenseQueryMetricCalculator()

    async def evaluate(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase],
    ) -> NiaCaseDenseQueryStrategyReport:
        variants = NiaCaseQueryVariantBuilder().build(queries)
        golden_by_id = {item.evaluation_id.value: item for item in golden_cases}
        if {item.evaluation_id for item in queries} != set(golden_by_id):
            raise RuntimeError("평가 질의와 골든셋 v4의 evaluation_id가 일치하지 않습니다.")

        embedding = await self._embedder.embed(
            EmbeddingRequest(texts=[item.query for item in variants])
        )
        if len(embedding.vectors) != len(variants):
            raise RuntimeError(
                "질의 전략 수와 임베딩 벡터 수가 다릅니다: "
                f"queries={len(variants)}, vectors={len(embedding.vectors)}"
            )
        if any(
            len(vector.values) != BGE_M3_EMBEDDING_DIMENSIONS
            for vector in embedding.vectors
        ):
            raise RuntimeError("질의 전략 평가에 1,024차원이 아닌 임베딩이 포함됐습니다.")

        results: list[NiaCaseDenseQueryResult] = []
        for variant, vector in zip(variants, embedding.vectors, strict=True):
            search = await self._retriever.search(
                CaseSearchRequest(
                    query=variant.query,
                    query_embedding=vector,
                    text_version=self.TEXT_VERSION,
                    embedding_model=embedding.model,
                    candidate_limit=DEFAULT_CASE_CANDIDATE_LIMIT,
                )
            )
            if search.status is not LookupStatus.SUCCESS:
                raise RuntimeError(
                    "Dense 질의 전략 검색에 실패했습니다: "
                    f"evaluation_id={variant.evaluation_id}, "
                    f"strategy={variant.strategy.value}, status={search.status.value}, "
                    f"detail={search.error_message or '없음'}"
                )
            if len(search.hits) != DEFAULT_CASE_CANDIDATE_LIMIT:
                raise RuntimeError(
                    "Dense 질의 전략 검색 결과가 Top-40을 충족하지 못했습니다: "
                    f"evaluation_id={variant.evaluation_id}, "
                    f"strategy={variant.strategy.value}, hits={len(search.hits)}"
                )
            hits = [
                NiaCaseDenseQueryHit(
                    case_id=hit.case_id,
                    rank=rank,
                    similarity=hit.vector_similarity,
                )
                for rank, hit in enumerate(search.hits, start=1)
            ]
            relevant_anchor_ids = golden_by_id[
                variant.evaluation_id
            ].relevant_case_ids
            results.append(
                NiaCaseDenseQueryResult(
                    evaluation_id=variant.evaluation_id,
                    cohort=variant.cohort,
                    strategy=variant.strategy,
                    query=variant.query,
                    relevant_anchor_ids=relevant_anchor_ids,
                    hits=hits,
                    metrics=self._calculator.calculate(hits, relevant_anchor_ids),
                )
            )
            print(
                f"{variant.evaluation_id}/{variant.strategy.value}: "
                f"recall@40={results[-1].metrics.anchor_recall_at_40:.3f}"
            )

        aggregates = [
            self._aggregate(strategy, slice_name, results)
            for strategy in NiaCaseQueryStrategy
            for slice_name in CorpusRelativeEvaluationSlice
        ]
        pairwise = self._compare_pairwise(results)
        return NiaCaseDenseQueryStrategyReport(
            query_count=len(queries),
            results=results,
            aggregates=aggregates,
            pairwise=pairwise,
            profile_summary_win_count=sum(
                item.outcome
                is NiaCaseQueryStrategyOutcome.PROFILE_SUMMARY_WINS
                for item in pairwise
            ),
            context_preserved_win_count=sum(
                item.outcome
                is NiaCaseQueryStrategyOutcome.CONTEXT_PRESERVED_WINS
                for item in pairwise
            ),
            tie_count=sum(
                item.outcome is NiaCaseQueryStrategyOutcome.TIE
                for item in pairwise
            ),
        )

    def _aggregate(
        self,
        strategy: NiaCaseQueryStrategy,
        slice_name: CorpusRelativeEvaluationSlice,
        results: list[NiaCaseDenseQueryResult],
    ) -> NiaCaseDenseQueryAggregate:
        selected = [
            item
            for item in results
            if item.strategy is strategy
            and (
                slice_name is CorpusRelativeEvaluationSlice.ALL
                or item.cohort.value == slice_name.value
            )
        ]
        relevant_selected = [
            item for item in selected if item.relevant_anchor_ids
        ]
        if not relevant_selected:
            raise RuntimeError(
                "관련 anchor가 있는 질의가 없어 평균 Recall을 계산할 수 없습니다: "
                f"strategy={strategy.value}, slice={slice_name.value}"
            )
        return NiaCaseDenseQueryAggregate(
            strategy=strategy,
            slice=slice_name,
            query_count=len(selected),
            anchor_success_at_20=fmean(
                item.metrics.anchor_success_at_20 for item in selected
            ),
            anchor_recall_at_20=fmean(
                item.metrics.anchor_recall_at_20 for item in relevant_selected
            ),
            anchor_success_at_40=fmean(
                item.metrics.anchor_success_at_40 for item in selected
            ),
            anchor_recall_at_40=fmean(
                item.metrics.anchor_recall_at_40 for item in relevant_selected
            ),
            mean_reciprocal_rank_at_40=fmean(
                item.metrics.reciprocal_rank_at_40 for item in relevant_selected
            ),
            mean_ndcg_at_40=fmean(
                item.metrics.ndcg_at_40 for item in relevant_selected
            ),
        )

    def _compare_pairwise(
        self,
        results: list[NiaCaseDenseQueryResult],
    ) -> list[NiaCaseDenseQueryPairwiseResult]:
        by_key = {
            (item.evaluation_id, item.strategy): item for item in results
        }
        evaluation_ids = sorted({item.evaluation_id for item in results})
        comparisons: list[NiaCaseDenseQueryPairwiseResult] = []
        for evaluation_id in evaluation_ids:
            profile = by_key[
                (evaluation_id, NiaCaseQueryStrategy.PROFILE_SUMMARY)
            ]
            context = by_key[
                (evaluation_id, NiaCaseQueryStrategy.CONTEXT_PRESERVED)
            ]
            profile_relevant = set(
                profile.metrics.retrieved_relevant_anchor_ids
            )
            context_relevant = set(
                context.metrics.retrieved_relevant_anchor_ids
            )
            profile_first_rank = self._first_relevant_rank(profile)
            context_first_rank = self._first_relevant_rank(context)
            comparisons.append(
                NiaCaseDenseQueryPairwiseResult(
                    evaluation_id=evaluation_id,
                    outcome=self._outcome(
                        profile_relevant,
                        context_relevant,
                        profile_first_rank,
                        context_first_rank,
                    ),
                    profile_summary_relevant_count=len(profile_relevant),
                    context_preserved_relevant_count=len(context_relevant),
                    profile_summary_first_relevant_rank=profile_first_rank,
                    context_preserved_first_relevant_rank=context_first_rank,
                    profile_summary_only_anchor_ids=sorted(
                        profile_relevant - context_relevant
                    ),
                    context_preserved_only_anchor_ids=sorted(
                        context_relevant - profile_relevant
                    ),
                    top40_overlap_count=len(
                        {item.case_id for item in profile.hits}
                        & {item.case_id for item in context.hits}
                    ),
                )
            )
        return comparisons

    def _first_relevant_rank(
        self,
        result: NiaCaseDenseQueryResult,
    ) -> int | None:
        relevant = set(result.relevant_anchor_ids)
        return next(
            (item.rank for item in result.hits if item.case_id in relevant),
            None,
        )

    def _outcome(
        self,
        profile_relevant: set[str],
        context_relevant: set[str],
        profile_first_rank: int | None,
        context_first_rank: int | None,
    ) -> NiaCaseQueryStrategyOutcome:
        profile_key = (
            len(profile_relevant),
            -(profile_first_rank or DEFAULT_CASE_CANDIDATE_LIMIT + 1),
        )
        context_key = (
            len(context_relevant),
            -(context_first_rank or DEFAULT_CASE_CANDIDATE_LIMIT + 1),
        )
        if profile_key > context_key:
            return NiaCaseQueryStrategyOutcome.PROFILE_SUMMARY_WINS
        if context_key > profile_key:
            return NiaCaseQueryStrategyOutcome.CONTEXT_PRESERVED_WINS
        return NiaCaseQueryStrategyOutcome.TIE


class NiaCaseDenseQueryStrategyMarkdownReporter:
    def render(self, report: NiaCaseDenseQueryStrategyReport) -> str:
        aggregates = {
            (item.strategy, item.slice): item for item in report.aggregates
        }
        summary_all = aggregates[
            (NiaCaseQueryStrategy.CONCERN_SUMMARY, CorpusRelativeEvaluationSlice.ALL)
        ]
        profile_all = aggregates[
            (NiaCaseQueryStrategy.PROFILE_SUMMARY, CorpusRelativeEvaluationSlice.ALL)
        ]
        context_all = aggregates[
            (NiaCaseQueryStrategy.CONTEXT_PRESERVED, CorpusRelativeEvaluationSlice.ALL)
        ]
        summary_rare = aggregates[
            (
                NiaCaseQueryStrategy.CONCERN_SUMMARY,
                CorpusRelativeEvaluationSlice.RARE_STRESS,
            )
        ]
        profile_rare = aggregates[
            (
                NiaCaseQueryStrategy.PROFILE_SUMMARY,
                CorpusRelativeEvaluationSlice.RARE_STRESS,
            )
        ]
        context_rare = aggregates[
            (
                NiaCaseQueryStrategy.CONTEXT_PRESERVED,
                CorpusRelativeEvaluationSlice.RARE_STRESS,
            )
        ]
        lines = [
            "# NIA Case 단일 질의 구성 Dense Top-40 비교",
            "",
            "## 실험 목적과 통제 조건",
            "",
            "- `concern_summary`: 핵심·보조 고민명만 남긴 축약 하한선",
            "- `profile_summary`: 나이·성별·계절·피부 타입·고민과 `피부 관련 성분 및 주의사항`을 결합한 기존 형식의 요약 질의",
            "- `context_preserved`: 나이·피부 타입·계절·부위·증상·요청 방향을 포함한 평가용 사용자 원문",
            "- 공통 조건: `BAAI/bge-m3`, 동일 DB, 동일 24개 질의, 동일 골든셋 v4, 질의당 Top-40",
            "- 이 단계에서는 metadata selector와 reranker를 적용하지 않았다.",
            "",
            "## 집계 결과",
            "",
            "| 구분 | 전략 | Success@20 | Recall@20 | Success@40 | Recall@40 | MRR@40 | nDCG@40 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for slice_name in CorpusRelativeEvaluationSlice:
            for strategy in NiaCaseQueryStrategy:
                item = aggregates[(strategy, slice_name)]
                lines.append(
                    f"| `{slice_name.value}` | `{strategy.value}` | "
                    f"{item.anchor_success_at_20:.3f} | "
                    f"{item.anchor_recall_at_20:.3f} | "
                    f"{item.anchor_success_at_40:.3f} | "
                    f"{item.anchor_recall_at_40:.3f} | "
                    f"{item.mean_reciprocal_rank_at_40:.3f} | "
                    f"{item.mean_ndcg_at_40:.3f} |"
                )
        lines.extend(
            [
                "",
                "## 질의별 대조",
                "",
                f"- 프로필 요약 질의 우세: {report.profile_summary_win_count}건",
                f"- 문맥 보존 질의 우세: {report.context_preserved_win_count}건",
                f"- 동률: {report.tie_count}건",
                "",
                "우세 판정은 먼저 Top-40 관련 anchor 회수 개수를 비교하고, 개수가 같으면 첫 관련 anchor의 순위가 높은 전략을 선택했다.",
                "",
                "| evaluation_id | 판정 | 프로필 요약 회수 | 문맥 회수 | 프로필 요약 첫 순위 | 문맥 첫 순위 | Top-40 교집합 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in report.pairwise:
            lines.append(
                f"| `{item.evaluation_id}` | `{item.outcome.value}` | "
                f"{item.profile_summary_relevant_count} | "
                f"{item.context_preserved_relevant_count} | "
                f"{item.profile_summary_first_relevant_rank or '-'} | "
                f"{item.context_preserved_first_relevant_rank or '-'} | "
                f"{item.top40_overlap_count} |"
            )
        lines.extend(
            [
                "",
                "## 해석 제한",
                "",
                "- Recall은 전체 3,581건의 완전 recall이 아니라 골든셋 v4의 초기 관련 anchor에 대한 회수율이다.",
                "- 골든셋에 없는 새 관련 Case가 한 전략에서만 검색될 수 있으므로, 이 결과는 고정 anchor 회수 비교로 해석한다.",
                "- 다음 metadata·reranker 실험에서는 각 전략의 신규 Top-3를 블라인드 판정한 뒤 모든 전략을 같은 확장 qrels로 다시 채점해야 한다.",
                "",
                "## 결론",
                "",
                (
                    "- 기본 검색 질의는 `context_preserved`를 유지한다. 전체 "
                    f"Recall@40이 프로필 요약 {profile_all.anchor_recall_at_40:.3f}에서 "
                    f"{context_all.anchor_recall_at_40:.3f}로 높고, MRR@40도 "
                    f"{profile_all.mean_reciprocal_rank_at_40:.3f}에서 "
                    f"{context_all.mean_reciprocal_rank_at_40:.3f}로 높다."
                ),
                (
                    "- 희소 스트레스셋에서는 프로필 요약형의 Recall@40이 "
                    f"{profile_rare.anchor_recall_at_40:.3f}으로 문맥 보존형 "
                    f"{context_rare.anchor_recall_at_40:.3f}보다 높지만, 첫 관련 문서 "
                    "순위는 문맥 보존형이 더 좋다."
                ),
                (
                    "- 고민명 축약 하한선의 전체 Recall@40은 "
                    f"{summary_all.anchor_recall_at_40:.3f}, 희소 Recall@40은 "
                    f"{summary_rare.anchor_recall_at_40:.3f}이다."
                ),
                "- 프로필 요약 질의를 기본값이나 전체 대체안으로 사용하지 않는다. 희소 고민 보완은 다음 metadata 적용 방식 비교에서 검증한다.",
                "",
            ]
        )
        return "\n".join(lines)


class NiaCaseDenseQueryStrategyCli:
    RUN_ID: ClassVar[str] = "query_strategy_dense_20260926_1709_v1"
    GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v4.jsonl"
    )
    RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_query_strategy_dense_results_20260926_1709_v1.jsonl"
    )
    SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_query_strategy_dense_summary_20260926_1709_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_1709_NIA_CASE_QUERY_STRATEGY_DENSE_EVAL_REPORT.md"
    )

    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        queries = NiaCaseSemanticEvaluationQueryLoader().load(
            NiaCaseCorpusRelativeEvaluationCli.QUERY_PATH
        ).items
        golden_cases = [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in cls.GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        config = TwoLayerAgentModelConfigFactory()
        database: Database = ConfiguredDatabaseFactory().create()
        try:
            report = await NiaCaseDenseQueryStrategyEvaluator(
                embedder=TextEmbedderFactory().create(config.create_embedding()),
                retriever=BackendNiaCaseRetriever(database.session_factory),
            ).evaluate(queries, golden_cases)
        finally:
            await database.dispose()

        writer = CandidatePoolJsonlWriter()
        writer.write(cls.RESULT_PATH, list(report.results))
        writer.write(cls.SUMMARY_PATH, [report])
        cls.REPORT_PATH.write_text(
            NiaCaseDenseQueryStrategyMarkdownReporter().render(report),
            encoding="utf-8",
        )
        all_aggregates = {
            item.strategy: item
            for item in report.aggregates
            if item.slice is CorpusRelativeEvaluationSlice.ALL
        }
        summary = all_aggregates[NiaCaseQueryStrategy.CONCERN_SUMMARY]
        context = all_aggregates[NiaCaseQueryStrategy.CONTEXT_PRESERVED]
        print(
            "NIA Case 질의 전략 Dense 평가 완료: "
            f"run_id={cls.RUN_ID}, "
            f"summary_recall@40={summary.anchor_recall_at_40:.3f}, "
            f"context_recall@40={context.anchor_recall_at_40:.3f}, "
            f"wins={report.profile_summary_win_count}/"
            f"{report.context_preserved_win_count}/{report.tie_count}"
        )


if __name__ == "__main__":
    asyncio.run(NiaCaseDenseQueryStrategyCli.main())
