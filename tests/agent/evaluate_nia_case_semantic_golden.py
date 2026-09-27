"""NIA Case 의미 골든셋으로 cached Top-40 → metadata Top-20 → reranker Top-3를 평가한다."""

from enum import StrEnum
from pathlib import Path
from statistics import fmean
from typing import ClassVar

from pydantic import Field

from agent.rag.case_schemas import (
    DEFAULT_CASE_CANDIDATE_LIMIT,
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseSearchHit,
)
from agent.rag.retrieval.case_candidate_selector import (
    CaseCandidateSelectionRequest,
    CaseMetadataCandidateSelector,
)
from agent.rag.schemas import RagModel
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    InternalCandidatePoolEntry,
    InternalCandidatePoolItem,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
    SemanticEvaluationCohort,
)
from tests.agent.nia_case_semantic_final_golden import (
    NiaCaseSemanticGoldenArtifact,
    NiaCaseSemanticGoldenCase,
    NiaCaseSemanticGradedQrel,
)
from tests.agent.nia_case_semantic_golden_schemas import FinalRelevanceGrade
from tests.agent.nia_case_semantic_metrics import (
    NiaCaseSemanticMetricScorer,
    RankedSemanticCase,
    SemanticRetrievalStage,
    SemanticStageRanking,
)
from tests.agent.nia_case_semantic_rerank_probe import (
    NiaCaseSemanticRerankProbeItem,
)


class SemanticEvaluationSlice(StrEnum):
    ALL = "all"
    CORE = "core"
    RARE_STRESS = "rare_stress"


class NiaCaseSemanticStageResult(RagModel):
    retrieved_count: int = Field(ge=1)
    judged_count: int = Field(ge=0)
    relevant_count: int = Field(ge=0)
    relevant_success: bool
    ceiling_hit: bool
    pooled_recall: float = Field(ge=0.0, le=1.0)
    judged_precision: float = Field(ge=0.0, le=1.0)


class NiaCaseSemanticTop3Result(RagModel):
    case_ids: list[str] = Field(min_length=3, max_length=3)
    grades: list[FinalRelevanceGrade] = Field(min_length=3, max_length=3)
    ndcg_at_3: float = Field(ge=0.0, le=1.0)
    precision_at_3: float = Field(ge=0.0, le=1.0)
    mrr_highly_relevant_at_3: float = Field(ge=0.0, le=1.0)
    highly_relevant_success: bool
    ceiling_hit: bool
    conflict_exposure_count: int = Field(ge=0, le=3)
    exact_duplicate_count: int = Field(ge=0, le=2)


class NiaCaseSemanticQueryEvaluation(RagModel):
    evaluation_id: str = Field(min_length=1)
    cohort: SemanticEvaluationCohort
    corpus_ceiling_grade: FinalRelevanceGrade
    judged_qrel_count: int = Field(ge=1)
    relevant_qrel_count: int = Field(ge=0)
    dense_top_40: NiaCaseSemanticStageResult
    metadata_top_20: NiaCaseSemanticStageResult
    top_3: NiaCaseSemanticTop3Result


class NiaCaseSemanticAggregate(RagModel):
    slice: SemanticEvaluationSlice
    query_count: int = Field(ge=1)
    dense_relevant_success: float = Field(ge=0.0, le=1.0)
    dense_ceiling_hit: float = Field(ge=0.0, le=1.0)
    dense_pooled_recall: float = Field(ge=0.0, le=1.0)
    dense_judged_precision: float = Field(ge=0.0, le=1.0)
    metadata_relevant_retention: float = Field(ge=0.0, le=1.0)
    metadata_ceiling_hit: float = Field(ge=0.0, le=1.0)
    top3_ndcg: float = Field(ge=0.0, le=1.0)
    top3_precision: float = Field(ge=0.0, le=1.0)
    top3_highly_relevant_success: float = Field(ge=0.0, le=1.0)
    top3_ceiling_hit: float = Field(ge=0.0, le=1.0)
    top3_conflict_exposure_count: int = Field(ge=0)
    top3_exact_duplicate_count: int = Field(ge=0)


class NiaCaseSemanticEvaluationReport(RagModel):
    queries: list[NiaCaseSemanticQueryEvaluation] = Field(min_length=1)
    aggregates: list[NiaCaseSemanticAggregate] = Field(min_length=1)


class NiaCaseSemanticRerankProbeLoader:
    def load(self, path: Path) -> list[NiaCaseSemanticRerankProbeItem]:
        try:
            return [
                NiaCaseSemanticRerankProbeItem.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValueError) as error:
            raise RuntimeError(f"reranker probe 결과를 읽지 못했습니다: {path}") from error


class NiaCaseSemanticGoldenEvaluator:
    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"
    PROVENANCE_ARCHIVE: ClassVar[str] = "semantic_evaluation_cached_pool"

    def __init__(self) -> None:
        self._selector = CaseMetadataCandidateSelector()
        self._metric_scorer = NiaCaseSemanticMetricScorer()

    def evaluate(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        golden_items: list[NiaCaseSemanticGoldenCase],
        internal_items: list[InternalCandidatePoolItem],
        probes: list[NiaCaseSemanticRerankProbeItem],
    ) -> NiaCaseSemanticEvaluationReport:
        golden_by_id = {item.evaluation_id: item for item in golden_items}
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        probes_by_id = {item.evaluation_id: item for item in probes}
        results = [
            self._evaluate_query(
                query=query,
                golden=golden_by_id[query.evaluation_id],
                internal=internal_by_id[query.evaluation_id],
                probe=probes_by_id[query.evaluation_id],
            )
            for query in queries
        ]
        return NiaCaseSemanticEvaluationReport(
            queries=results,
            aggregates=[
                self._aggregate(SemanticEvaluationSlice.ALL, results),
                self._aggregate(
                    SemanticEvaluationSlice.CORE,
                    [item for item in results if item.cohort is SemanticEvaluationCohort.CORE],
                ),
                self._aggregate(
                    SemanticEvaluationSlice.RARE_STRESS,
                    [
                        item
                        for item in results
                        if item.cohort is SemanticEvaluationCohort.RARE_STRESS
                    ],
                ),
            ],
        )

    def _evaluate_query(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        golden: NiaCaseSemanticGoldenCase,
        internal: InternalCandidatePoolItem,
        probe: NiaCaseSemanticRerankProbeItem,
    ) -> NiaCaseSemanticQueryEvaluation:
        qrels_by_id = {item.case_id: item for item in golden.graded_qrels}
        dense_entries = [
            item
            for item in internal.candidates
            if item.dense_rank is not None
            and item.dense_rank <= DEFAULT_CASE_CANDIDATE_LIMIT
        ]
        dense_entries.sort(key=lambda item: (item.dense_rank or 0, item.case_id))
        selection = self._selector.select(
            CaseCandidateSelectionRequest(
                query=query.query,
                skin_concerns=[
                    concern.value
                    for concern in [*query.primary_concerns, *query.secondary_concerns]
                ],
                candidates=[self._to_search_hit(item) for item in dense_entries],
            )
        )
        metadata_ids = [item.case_id for item in selection.candidates]
        top3_ids = [item.case_id for item in probe.hits]
        missing_top3 = [case_id for case_id in top3_ids if case_id not in qrels_by_id]
        if missing_top3:
            raise RuntimeError(
                f"Top-3에 미판정 Case가 남아 있습니다: {query.evaluation_id}, {missing_top3}"
            )
        all_relevant = {
            item.case_id
            for item in golden.graded_qrels
            if item.relevance_grade >= FinalRelevanceGrade.RELEVANT
        }
        dense_result = self._stage_result(
            retrieved_ids=[item.case_id for item in dense_entries],
            qrels_by_id=qrels_by_id,
            all_relevant=all_relevant,
            ceiling=golden.corpus_ceiling_grade,
        )
        metadata_result = self._stage_result(
            retrieved_ids=metadata_ids,
            qrels_by_id=qrels_by_id,
            all_relevant=all_relevant,
            ceiling=golden.corpus_ceiling_grade,
        )
        top3_qrels = [qrels_by_id[case_id] for case_id in top3_ids]
        ranking = SemanticStageRanking(
            stage=SemanticRetrievalStage.RERANKER_TOP_3,
            items=[
                RankedSemanticCase(
                    review_key=qrel.review_key,
                    rank=rank,
                    relevance_grade=qrel.relevance_grade,
                )
                for rank, qrel in enumerate(top3_qrels, start=1)
            ],
        )
        metric = self._metric_scorer.score_stage(
            ranking=ranking,
            all_judged_grades=[item.relevance_grade for item in golden.graded_qrels],
        )
        content_by_id = {
            item.case_id: (item.question, item.answer) for item in internal.candidates
        }
        top3_content = [content_by_id[case_id] for case_id in top3_ids]
        return NiaCaseSemanticQueryEvaluation(
            evaluation_id=query.evaluation_id,
            cohort=query.cohort,
            corpus_ceiling_grade=golden.corpus_ceiling_grade,
            judged_qrel_count=len(golden.graded_qrels),
            relevant_qrel_count=len(all_relevant),
            dense_top_40=dense_result,
            metadata_top_20=metadata_result,
            top_3=NiaCaseSemanticTop3Result(
                case_ids=top3_ids,
                grades=[item.relevance_grade for item in top3_qrels],
                ndcg_at_3=metric.ndcg or 0.0,
                precision_at_3=sum(
                    item.relevance_grade >= FinalRelevanceGrade.RELEVANT
                    for item in top3_qrels
                )
                / 3,
                mrr_highly_relevant_at_3=self._mrr_highly_relevant(top3_qrels),
                highly_relevant_success=any(
                    item.relevance_grade is FinalRelevanceGrade.HIGHLY_RELEVANT
                    for item in top3_qrels
                ),
                ceiling_hit=metric.ceiling_hit,
                conflict_exposure_count=sum(bool(item.conflict_codes) for item in top3_qrels),
                exact_duplicate_count=len(top3_content) - len(set(top3_content)),
            ),
        )

    def _stage_result(
        self,
        retrieved_ids: list[str],
        qrels_by_id: dict[str, NiaCaseSemanticGradedQrel],
        all_relevant: set[str],
        ceiling: FinalRelevanceGrade,
    ) -> NiaCaseSemanticStageResult:
        judged = [qrels_by_id[item] for item in retrieved_ids if item in qrels_by_id]
        relevant = [
            item for item in judged if item.relevance_grade >= FinalRelevanceGrade.RELEVANT
        ]
        best = max(
            (item.relevance_grade for item in judged),
            default=FinalRelevanceGrade.NOT_RELEVANT,
        )
        return NiaCaseSemanticStageResult(
            retrieved_count=len(retrieved_ids),
            judged_count=len(judged),
            relevant_count=len(relevant),
            relevant_success=bool(relevant),
            ceiling_hit=best is ceiling,
            pooled_recall=(
                len(set(retrieved_ids) & all_relevant) / len(all_relevant)
                if all_relevant
                else 1.0
            ),
            judged_precision=len(relevant) / len(judged) if judged else 0.0,
        )

    def _mrr_highly_relevant(self, qrels: list[NiaCaseSemanticGradedQrel]) -> float:
        for rank, item in enumerate(qrels, start=1):
            if item.relevance_grade is FinalRelevanceGrade.HIGHLY_RELEVANT:
                return 1.0 / rank
        return 0.0

    def _aggregate(
        self,
        slice_name: SemanticEvaluationSlice,
        items: list[NiaCaseSemanticQueryEvaluation],
    ) -> NiaCaseSemanticAggregate:
        dense_relevant_counts = [item.dense_top_40.relevant_count for item in items]
        metadata_relevant_counts = [item.metadata_top_20.relevant_count for item in items]
        return NiaCaseSemanticAggregate(
            slice=slice_name,
            query_count=len(items),
            dense_relevant_success=fmean(item.dense_top_40.relevant_success for item in items),
            dense_ceiling_hit=fmean(item.dense_top_40.ceiling_hit for item in items),
            dense_pooled_recall=fmean(item.dense_top_40.pooled_recall for item in items),
            dense_judged_precision=fmean(
                item.dense_top_40.judged_precision for item in items
            ),
            metadata_relevant_retention=fmean(
                metadata / dense if dense else 1.0
                for metadata, dense in zip(
                    metadata_relevant_counts,
                    dense_relevant_counts,
                    strict=True,
                )
            ),
            metadata_ceiling_hit=fmean(item.metadata_top_20.ceiling_hit for item in items),
            top3_ndcg=fmean(item.top_3.ndcg_at_3 for item in items),
            top3_precision=fmean(item.top_3.precision_at_3 for item in items),
            top3_highly_relevant_success=fmean(
                item.top_3.highly_relevant_success for item in items
            ),
            top3_ceiling_hit=fmean(item.top_3.ceiling_hit for item in items),
            top3_conflict_exposure_count=sum(
                item.top_3.conflict_exposure_count for item in items
            ),
            top3_exact_duplicate_count=sum(
                item.top_3.exact_duplicate_count for item in items
            ),
        )

    def _to_search_hit(self, item: InternalCandidatePoolEntry) -> CaseSearchHit:
        if item.dense_similarity is None:
            raise RuntimeError(f"dense 후보에 similarity가 없습니다: {item.case_id}")
        return CaseSearchHit(
            case_id=item.case_id,
            page_content=f"[질문]\n{item.question}\n\n[답변]\n{item.answer}",
            text_version=self.TEXT_VERSION,
            dataset_split=CaseDatasetSplit(item.dataset_split),
            metadata=CaseMetadata(
                target_concern=item.target_concern,
                gender=item.gender,
                age=item.age,
                skin_type=item.skin_type,
                skin_concerns=item.skin_concerns,
            ),
            provenance=CaseProvenance(
                archive_name=self.PROVENANCE_ARCHIVE,
                line_number=1,
            ),
            vector_similarity=item.dense_similarity,
        )


class NiaCaseSemanticEvaluationWriter:
    def write_jsonl(
        self,
        path: Path,
        report: NiaCaseSemanticEvaluationReport,
    ) -> None:
        try:
            with path.open("w", encoding="utf-8", newline="\n") as destination:
                for item in report.queries:
                    destination.write(item.model_dump_json())
                    destination.write("\n")
        except OSError as error:
            raise RuntimeError(f"의미 검색 평가 JSONL을 쓰지 못했습니다: {path}") from error

    def write_markdown(
        self,
        path: Path,
        report: NiaCaseSemanticEvaluationReport,
    ) -> None:
        lines = [
            "# NIA Case RAG Semantic Golden 평가 보고서",
            "",
            "## 평가 범위",
            "",
            "- 동결 사용자 질의 40개(핵심 30개, 희소 스트레스 10개)",
            "- BGE-M3 cached dense Top-40 → 고민 메타데이터 Top-20 → bge-reranker-v2-m3 Top-3",
            "- 최초 anchor 600건과 실제 Top-3 보완 81건, 총 681 graded qrels",
            "- 미판정 문서를 비관련으로 간주하지 않는 pooled-anchor 평가",
            "",
            "## 종합 결과",
            "",
            "| 구간 | 질의 | Dense Relevant Success@40 | Dense Ceiling Hit@40 | Pooled Recall@40 | Judged Precision@40 | Metadata Relevant Retention@20 | Metadata Ceiling Hit@20 | nDCG@3 | Precision@3 | Highly Relevant Success@3 | Ceiling Hit@3 | 충돌 노출 | Top-3 정확 중복 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for item in report.aggregates:
            lines.append(
                f"| {item.slice.value} | {item.query_count} | "
                f"{item.dense_relevant_success:.1%} | {item.dense_ceiling_hit:.1%} | "
                f"{item.dense_pooled_recall:.1%} | {item.dense_judged_precision:.1%} | "
                f"{item.metadata_relevant_retention:.1%} | {item.metadata_ceiling_hit:.1%} | "
                f"{item.top3_ndcg:.3f} | {item.top3_precision:.1%} | "
                f"{item.top3_highly_relevant_success:.1%} | {item.top3_ceiling_hit:.1%} | "
                f"{item.top3_conflict_exposure_count} | {item.top3_exact_duplicate_count} |"
            )
        lines.extend(
            [
                "",
                "## 질의별 결과",
                "",
                "| evaluation_id | cohort | ceiling | qrels | relevant | dense recall | metadata retention | Top-3 grades | nDCG@3 | ceiling hit | conflicts |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |",
            ]
        )
        for item in report.queries:
            retention = (
                item.metadata_top_20.relevant_count / item.dense_top_40.relevant_count
                if item.dense_top_40.relevant_count
                else 1.0
            )
            lines.append(
                f"| {item.evaluation_id} | {item.cohort.value} | "
                f"{item.corpus_ceiling_grade.value} | {item.judged_qrel_count} | "
                f"{item.relevant_qrel_count} | {item.dense_top_40.pooled_recall:.1%} | "
                f"{retention:.1%} | "
                f"{','.join(str(grade.value) for grade in item.top_3.grades)} | "
                f"{item.top_3.ndcg_at_3:.3f} | "
                f"{'yes' if item.top_3.ceiling_hit else 'no'} | "
                f"{item.top_3.conflict_exposure_count} |"
            )
        core = next(
            item for item in report.aggregates if item.slice is SemanticEvaluationSlice.CORE
        )
        conflict_queries = [
            item.evaluation_id
            for item in report.queries
            if item.top_3.conflict_exposure_count > 0
        ]
        dense_failures = [
            item.evaluation_id
            for item in report.queries
            if not item.dense_top_40.relevant_success
        ]
        lowest_ndcg = sorted(report.queries, key=lambda item: item.top_3.ndcg_at_3)[:5]
        lines.extend(
            [
                "",
                "## 현재 설정에 대한 판정",
                "",
                f"- 핵심셋 Dense Relevant Success@40은 {core.dense_relevant_success:.1%}로 초기 90% 목표에 도달했다.",
                f"- 핵심셋 metadata relevant retention은 {core.metadata_relevant_retention:.1%}다. 다만 이는 최고 등급 후보 보존율과 동일한 지표가 아니므로 95% 목표와 직접 등치하지 않는다.",
                f"- 핵심셋 nDCG@3은 {core.top3_ndcg:.3f}로 초기 0.75 목표보다 낮다.",
                f"- 핵심셋 Highly Relevant Success@3은 {core.top3_highly_relevant_success:.1%}로 초기 80% 목표보다 낮다.",
                f"- Top-3 추천 충돌 문서는 전체 {core.top3_conflict_exposure_count + next(item for item in report.aggregates if item.slice is SemanticEvaluationSlice.RARE_STRESS).top3_conflict_exposure_count}건으로, 0건 목표를 충족하지 못했다.",
                "- 현재 병목은 Top-40 후보 수보다, 현재 증상과 반대되는 활성 성분 권고를 Top-3에서 내리지 못하는 재정렬 단계다.",
                "",
                "### 우선 검토 질의",
                "",
                f"- Top-3 충돌 노출: {', '.join(conflict_queries)}",
                f"- Dense Top-40 내 2점 이상 anchor 없음: {', '.join(dense_failures)}",
                "- nDCG@3 최저 5건: "
                + ", ".join(
                    f"{item.evaluation_id}({item.top_3.ndcg_at_3:.3f})"
                    for item in lowest_ndcg
                ),
            ]
        )
        lines.extend(
            [
                "",
                "## 해석 시 주의사항",
                "",
                "- `Pooled Recall@40`의 분모는 681건 판정 풀에서 2~3점인 대표 anchor다. 전체 DB의 모든 관련 Case를 뜻하지 않는다.",
                "- `Judged Precision@40`은 Top-40 중 판정된 문서만 분모로 삼는다. 미판정 문서를 0점으로 처리하지 않는다.",
                "- Top-3는 실제 노출 120건을 모두 판정했으므로 nDCG·Precision·충돌 노출을 직접 해석할 수 있다.",
                "- `corpus_ceiling_grade`는 전체 3,581건 전수 판정 상한이 아니라 현재 pooled anchor에서 확인된 최고 등급이다.",
            ]
        )
        try:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as error:
            raise RuntimeError(f"의미 검색 평가 보고서를 쓰지 못했습니다: {path}") from error


class NiaCaseSemanticEvaluationCli:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    GOLDEN_PATH: ClassVar[Path] = Path("tests/agent/nia_case_eval_data/nia_case_semantic_golden_v1.jsonl")
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    RERANK_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_rerank_probe_v1.jsonl"
    )
    OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_results_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_0112_NIA_CASE_SEMANTIC_GOLDEN_EVAL_REPORT.md"
    )

    @classmethod
    def main(cls) -> None:
        report = NiaCaseSemanticGoldenEvaluator().evaluate(
            queries=NiaCaseSemanticEvaluationQueryLoader().load(cls.QUERY_PATH).items,
            golden_items=NiaCaseSemanticGoldenArtifact().load(cls.GOLDEN_PATH).items,
            internal_items=CandidatePoolArtifactLoader().load_internal(
                cls.INTERNAL_POOL_PATH
            ),
            probes=NiaCaseSemanticRerankProbeLoader().load(cls.RERANK_PROBE_PATH),
        )
        writer = NiaCaseSemanticEvaluationWriter()
        writer.write_jsonl(cls.OUTPUT_PATH, report)
        writer.write_markdown(cls.REPORT_PATH, report)
        print(report.model_dump_json(indent=2, include={"aggregates"}))


if __name__ == "__main__":
    NiaCaseSemanticEvaluationCli.main()
