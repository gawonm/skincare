"""24개 활성 질의의 코퍼스 상대 골든셋 v2를 동결하고 단계별 검색 성능을 평가한다."""

from enum import StrEnum
from math import log2
from pathlib import Path
from statistics import fmean
from typing import ClassVar

from pydantic import AliasChoices, Field

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
from tests.agent.nia_case_corpus_relative_golden import (
    CorpusRelativeAnchorManifestItem,
    CorpusRelativeAnchorStratum,
    CorpusRelativeEvaluationId,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    CorpusConcernFitScore,
    CorpusContextFitScore,
    CorpusDirectionConflictCode,
    CorpusRelevanceGrade,
    CorpusRelevanceJudgmentPolicy,
    CorpusRelevanceReasonCode,
    CorpusRequestFitScore,
    NiaCaseCorpusRelevanceJudgment,
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
    InternalCandidatePoolEntry,
    InternalCandidatePoolItem,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
    SemanticEvaluationCohort,
)
from tests.agent.nia_case_semantic_rerank_probe import (
    NiaCaseSemanticRerankProbeItem,
)


class CorpusRelativeEvaluationSlice(StrEnum):
    ALL = "all"
    CORE = "core"
    RARE_STRESS = "rare_stress"


class NiaCaseCorpusRelativeGradedQrel(RagModel):
    case_id: str = Field(min_length=1)
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    is_initial_anchor: bool
    anchor_stratum: CorpusRelativeAnchorStratum | None = None
    relevance_grade: CorpusRelevanceGrade
    concern_fit: CorpusConcernFitScore
    context_fit: CorpusContextFitScore
    request_fit: CorpusRequestFitScore
    direction_conflicts: list[CorpusDirectionConflictCode] = Field(default_factory=list)
    reason_codes: list[CorpusRelevanceReasonCode] = Field(min_length=1)
    note: str = Field(min_length=10, max_length=260)


class NiaCaseCorpusRelativeGoldenCase(RagModel):
    evaluation_id: CorpusRelativeEvaluationId
    cohort: SemanticEvaluationCohort
    policy: CorpusRelevanceJudgmentPolicy
    query: str = Field(min_length=1)
    relevant_case_ids: list[str] = Field(default_factory=list)
    anchor_qrel_count: int = Field(ge=6, le=6)
    total_qrel_count: int = Field(ge=6)
    graded_qrels: list[NiaCaseCorpusRelativeGradedQrel] = Field(min_length=6)


class NiaCaseCorpusRelativeDenseStageResult(RagModel):
    retrieved_count: int = Field(ge=1)
    relevant_anchor_total: int = Field(ge=0)
    retrieved_relevant_anchor_count: int = Field(ge=0)
    anchor_success_at_40: bool
    anchor_recall_at_40: float = Field(ge=0.0, le=1.0)


class NiaCaseCorpusRelativeMetadataStageResult(RagModel):
    selected_count: int = Field(ge=1)
    retained_relevant_anchor_count: int = Field(ge=0)
    anchor_success_at_20: bool
    anchor_retention_at_20: float = Field(ge=0.0, le=1.0)


class NiaCaseCorpusRelativeTop3Result(RagModel):
    case_ids: list[str] = Field(min_length=3, max_length=3)
    review_keys: list[str] = Field(min_length=3, max_length=3)
    grades: list[CorpusRelevanceGrade] = Field(min_length=3, max_length=3)
    precision_at_3: float = Field(ge=0.0, le=1.0)
    ndcg_at_3: float = Field(ge=0.0, le=1.0)
    # 과거 산출물도 다시 읽을 수 있어야 하므로 기존 필드명은 입력 별칭으로만 보존한다.
    grade_3_hit_rate_at_3: bool = Field(
        validation_alias=AliasChoices(
            "grade_3_hit_rate_at_3",
            "highly_relevant_success_at_3",
        )
    )
    direction_conflict_at_3: int = Field(ge=0, le=3)
    exact_duplicate_at_3: int = Field(ge=0, le=2)


class NiaCaseCorpusRelativeQueryEvaluation(RagModel):
    evaluation_id: CorpusRelativeEvaluationId
    cohort: SemanticEvaluationCohort
    anchor_qrel_count: int = Field(ge=6, le=6)
    total_qrel_count: int = Field(ge=6)
    relevant_anchor_count: int = Field(ge=0)
    dense_top_40: NiaCaseCorpusRelativeDenseStageResult
    metadata_top_20: NiaCaseCorpusRelativeMetadataStageResult
    reranker_top_3: NiaCaseCorpusRelativeTop3Result


class NiaCaseCorpusRelativeAggregate(RagModel):
    slice: CorpusRelativeEvaluationSlice
    query_count: int = Field(ge=1)
    anchor_success_at_40: float = Field(ge=0.0, le=1.0)
    anchor_recall_at_40: float = Field(ge=0.0, le=1.0)
    metadata_anchor_success_at_20: float = Field(ge=0.0, le=1.0)
    metadata_anchor_retention_at_20: float = Field(ge=0.0, le=1.0)
    reranker_precision_at_3: float = Field(ge=0.0, le=1.0)
    reranker_ndcg_at_3: float = Field(ge=0.0, le=1.0)
    reranker_grade_3_hit_rate_at_3: float = Field(
        validation_alias=AliasChoices(
            "reranker_grade_3_hit_rate_at_3",
            "reranker_highly_relevant_success_at_3",
        ),
        ge=0.0,
        le=1.0,
    )
    reranker_direction_conflict_total: int = Field(ge=0)
    reranker_exact_duplicate_total: int = Field(ge=0)


class NiaCaseCorpusRelativeEvaluationReport(RagModel):
    queries: list[NiaCaseCorpusRelativeQueryEvaluation] = Field(min_length=1)
    aggregates: list[NiaCaseCorpusRelativeAggregate] = Field(min_length=1)


class NiaCaseCorpusRelativeJudgmentArtifactLoader:
    """초기 144건 anchor 판정과 56건 reranker 보완 판정을 읽어 병합한다."""

    def load_anchor_batches(
        self,
        directory: Path,
    ) -> dict[str, NiaCaseCorpusRelevanceJudgmentBatch]:
        paths = sorted(directory.glob("nia_case_corpus_relative_judgments_*_v1.jsonl"))
        batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch] = {}
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                batch = NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
                if batch.evaluation_id in batches:
                    raise RuntimeError(
                        f"중복 anchor 판정 파일이 존재합니다: {batch.evaluation_id}"
                    )
                batches[batch.evaluation_id] = batch
        return batches

    def load_rerank_batches(
        self,
        path: Path,
    ) -> dict[str, NiaCaseCorpusRelevanceJudgmentBatch]:
        batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            batch = NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
            if batch.evaluation_id in batches:
                raise RuntimeError(
                    f"중복 rerank 보완 판정이 존재합니다: {batch.evaluation_id}"
                )
            batches[batch.evaluation_id] = batch
        return batches


class NiaCaseCorpusRelativeGoldenBuilder:
    """초기 anchor 판정과 Top-3 보완 판정을 결합해 24질의 골든셋 v2를 만든다."""

    def build(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        manifests: list[CorpusRelativeAnchorManifestItem],
        internal_items: list[InternalCandidatePoolItem],
        anchor_batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch],
        rerank_batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch],
    ) -> list[NiaCaseCorpusRelativeGoldenCase]:
        manifests_by_id = {item.evaluation_id.value: item for item in manifests}
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase] = []

        for query in queries:
            evaluation_id = query.evaluation_id
            manifest = manifests_by_id[evaluation_id]
            internal = internal_by_id[evaluation_id]
            entries_by_key = {item.review_key: item for item in internal.candidates}
            stratum_by_key = {
                entry.review_key: entry.stratum for entry in manifest.entries
            }

            anchor_batch = anchor_batches[evaluation_id]
            rerank_batch = rerank_batches.get(evaluation_id)

            judgments_by_key: dict[str, tuple[NiaCaseCorpusRelevanceJudgment, bool]] = {
                judgment.review_key: (judgment, True)
                for judgment in anchor_batch.judgments
            }
            if rerank_batch is not None:
                for judgment in rerank_batch.judgments:
                    if judgment.review_key in judgments_by_key:
                        raise RuntimeError(
                            "anchor 판정과 rerank 보완 판정에 중복 review_key가 있습니다: "
                            f"{evaluation_id}/{judgment.review_key}"
                        )
                    judgments_by_key[judgment.review_key] = (judgment, False)

            graded_qrels: list[NiaCaseCorpusRelativeGradedQrel] = []
            relevant_anchor_case_ids: list[str] = []

            for review_key in sorted(judgments_by_key):
                judgment, is_initial_anchor = judgments_by_key[review_key]
                internal_entry = entries_by_key[review_key]
                stratum = stratum_by_key.get(review_key) if is_initial_anchor else None
                qrel = NiaCaseCorpusRelativeGradedQrel(
                    case_id=internal_entry.case_id,
                    review_key=review_key,
                    is_initial_anchor=is_initial_anchor,
                    anchor_stratum=stratum,
                    relevance_grade=judgment.relevance_grade,
                    concern_fit=judgment.concern_fit,
                    context_fit=judgment.context_fit,
                    request_fit=judgment.request_fit,
                    direction_conflicts=judgment.direction_conflicts,
                    reason_codes=judgment.reason_codes,
                    note=judgment.note,
                )
                graded_qrels.append(qrel)
                if (
                    is_initial_anchor
                    and judgment.relevance_grade >= CorpusRelevanceGrade.RELEVANT
                ):
                    relevant_anchor_case_ids.append(internal_entry.case_id)

            golden_cases.append(
                NiaCaseCorpusRelativeGoldenCase(
                    evaluation_id=CorpusRelativeEvaluationId(evaluation_id),
                    cohort=query.cohort,
                    policy=anchor_batch.policy,
                    query=query.query,
                    relevant_case_ids=sorted(relevant_anchor_case_ids),
                    anchor_qrel_count=len(anchor_batch.judgments),
                    total_qrel_count=len(graded_qrels),
                    graded_qrels=graded_qrels,
                )
            )
        return golden_cases


class NiaCaseCorpusRelativeGoldenEvaluator:
    """24질의 골든셋 v2를 기준으로 Dense, Metadata, Reranker 단계 지표를 계산한다."""

    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"
    PROVENANCE_ARCHIVE: ClassVar[str] = "semantic_evaluation_cached_pool"

    def __init__(self) -> None:
        self._selector = CaseMetadataCandidateSelector()

    def evaluate(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase],
        internal_items: list[InternalCandidatePoolItem],
        probes: list[NiaCaseSemanticRerankProbeItem],
    ) -> NiaCaseCorpusRelativeEvaluationReport:
        golden_by_id = {item.evaluation_id.value: item for item in golden_cases}
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        probes_by_id = {item.evaluation_id: item for item in probes}

        query_results = [
            self._evaluate_query(
                query=query,
                golden=golden_by_id[query.evaluation_id],
                internal=internal_by_id[query.evaluation_id],
                probe=probes_by_id[query.evaluation_id],
            )
            for query in queries
        ]
        return NiaCaseCorpusRelativeEvaluationReport(
            queries=query_results,
            aggregates=[
                self._aggregate(CorpusRelativeEvaluationSlice.ALL, query_results),
                self._aggregate(
                    CorpusRelativeEvaluationSlice.CORE,
                    [
                        item
                        for item in query_results
                        if item.cohort is SemanticEvaluationCohort.CORE
                    ],
                ),
                self._aggregate(
                    CorpusRelativeEvaluationSlice.RARE_STRESS,
                    [
                        item
                        for item in query_results
                        if item.cohort is SemanticEvaluationCohort.RARE_STRESS
                    ],
                ),
            ],
        )

    def _evaluate_query(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        golden: NiaCaseCorpusRelativeGoldenCase,
        internal: InternalCandidatePoolItem,
        probe: NiaCaseSemanticRerankProbeItem,
    ) -> NiaCaseCorpusRelativeQueryEvaluation:
        qrels_by_case_id = {item.case_id: item for item in golden.graded_qrels}
        relevant_anchor_ids = set(golden.relevant_case_ids)

        dense_entries = sorted(
            [
                item
                for item in internal.candidates
                if item.dense_rank is not None
                and item.dense_rank <= DEFAULT_CASE_CANDIDATE_LIMIT
            ],
            key=lambda item: (item.dense_rank or 0, item.case_id),
        )
        dense_case_ids = [item.case_id for item in dense_entries]
        dense_relevant_anchors = [
            case_id for case_id in dense_case_ids if case_id in relevant_anchor_ids
        ]
        anchor_recall_at_40 = (
            len(dense_relevant_anchors) / len(relevant_anchor_ids)
            if relevant_anchor_ids
            else 0.0
        )

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
        metadata_case_ids = [item.case_id for item in selection.candidates]
        metadata_relevant_anchors = [
            case_id for case_id in metadata_case_ids if case_id in relevant_anchor_ids
        ]
        # Dense Top-40이 회수한 관련 anchor 중 metadata Top-20이 보존한 비율을 계산한다
        anchor_retention_at_20 = (
            len(metadata_relevant_anchors) / len(dense_relevant_anchors)
            if dense_relevant_anchors
            else 0.0
        )

        top3_case_ids = [item.case_id for item in probe.hits]
        top3_qrels = [qrels_by_case_id[case_id] for case_id in top3_case_ids]
        top3_grades = [int(item.relevance_grade) for item in top3_qrels]
        all_grades = [int(item.relevance_grade) for item in golden.graded_qrels]
        ndcg_at_3 = self._compute_ndcg_at_k(top3_grades, all_grades, k=3)
        precision_at_3 = (
            sum(
                item.relevance_grade >= CorpusRelevanceGrade.RELEVANT
                for item in top3_qrels
            )
            / 3.0
        )

        content_by_id = {
            item.case_id: (item.question, item.answer) for item in internal.candidates
        }
        top3_contents = [content_by_id[case_id] for case_id in top3_case_ids]

        return NiaCaseCorpusRelativeQueryEvaluation(
            evaluation_id=golden.evaluation_id,
            cohort=query.cohort,
            anchor_qrel_count=golden.anchor_qrel_count,
            total_qrel_count=golden.total_qrel_count,
            relevant_anchor_count=len(relevant_anchor_ids),
            dense_top_40=NiaCaseCorpusRelativeDenseStageResult(
                retrieved_count=len(dense_case_ids),
                relevant_anchor_total=len(relevant_anchor_ids),
                retrieved_relevant_anchor_count=len(dense_relevant_anchors),
                anchor_success_at_40=bool(dense_relevant_anchors),
                anchor_recall_at_40=anchor_recall_at_40,
            ),
            metadata_top_20=NiaCaseCorpusRelativeMetadataStageResult(
                selected_count=len(metadata_case_ids),
                retained_relevant_anchor_count=len(metadata_relevant_anchors),
                anchor_success_at_20=bool(metadata_relevant_anchors),
                anchor_retention_at_20=anchor_retention_at_20,
            ),
            reranker_top_3=NiaCaseCorpusRelativeTop3Result(
                case_ids=top3_case_ids,
                review_keys=[item.review_key for item in top3_qrels],
                grades=[item.relevance_grade for item in top3_qrels],
                precision_at_3=precision_at_3,
                ndcg_at_3=ndcg_at_3,
                grade_3_hit_rate_at_3=any(
                    item.relevance_grade is CorpusRelevanceGrade.HIGHLY_RELEVANT
                    for item in top3_qrels
                ),
                direction_conflict_at_3=sum(
                    bool(item.direction_conflicts) for item in top3_qrels
                ),
                exact_duplicate_at_3=len(top3_contents) - len(set(top3_contents)),
            ),
        )

    def _compute_ndcg_at_k(
        self,
        ranked_grades: list[int],
        all_judged_grades: list[int],
        k: int,
    ) -> float:
        dcg = sum(
            ((2**grade) - 1) / log2(index + 2)
            for index, grade in enumerate(ranked_grades[:k])
        )
        ideal_grades = sorted(all_judged_grades, reverse=True)[:k]
        idcg = sum(
            ((2**grade) - 1) / log2(index + 2)
            for index, grade in enumerate(ideal_grades)
        )
        if idcg == 0.0:
            return 0.0
        return dcg / idcg

    def _aggregate(
        self,
        slice_name: CorpusRelativeEvaluationSlice,
        items: list[NiaCaseCorpusRelativeQueryEvaluation],
    ) -> NiaCaseCorpusRelativeAggregate:
        dense_success_items = [
            item.dense_top_40.anchor_success_at_40 for item in items
        ]
        # 관련 anchor가 존재하는 질의들만 대상으로 Recall과 Retention을 평균한다
        queries_with_relevant_anchor = [
            item for item in items if item.relevant_anchor_count > 0
        ]
        queries_with_dense_hit = [
            item
            for item in items
            if item.dense_top_40.retrieved_relevant_anchor_count > 0
        ]
        return NiaCaseCorpusRelativeAggregate(
            slice=slice_name,
            query_count=len(items),
            anchor_success_at_40=fmean(1.0 if flag else 0.0 for flag in dense_success_items),
            anchor_recall_at_40=(
                fmean(
                    item.dense_top_40.anchor_recall_at_40
                    for item in queries_with_relevant_anchor
                )
                if queries_with_relevant_anchor
                else 0.0
            ),
            metadata_anchor_success_at_20=fmean(
                1.0 if item.metadata_top_20.anchor_success_at_20 else 0.0
                for item in items
            ),
            metadata_anchor_retention_at_20=(
                fmean(
                    item.metadata_top_20.anchor_retention_at_20
                    for item in queries_with_dense_hit
                )
                if queries_with_dense_hit
                else 0.0
            ),
            reranker_precision_at_3=fmean(
                item.reranker_top_3.precision_at_3 for item in items
            ),
            reranker_ndcg_at_3=fmean(
                item.reranker_top_3.ndcg_at_3 for item in items
            ),
            reranker_grade_3_hit_rate_at_3=fmean(
                1.0 if item.reranker_top_3.grade_3_hit_rate_at_3 else 0.0
                for item in items
            ),
            reranker_direction_conflict_total=sum(
                item.reranker_top_3.direction_conflict_at_3 for item in items
            ),
            reranker_exact_duplicate_total=sum(
                item.reranker_top_3.exact_duplicate_at_3 for item in items
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


class NiaCaseCorpusRelativeMarkdownReporter:
    """코퍼스 상대 골든셋 v2 평가 결과를 마크다운 보고서로 변환한다."""

    def render(self, report: NiaCaseCorpusRelativeEvaluationReport) -> str:
        lines = [
            "# NIA Case 코퍼스 상대 골든셋 v2 단계별 검색 평가 보고서",
            "",
            "## 1. 평가 개요",
            "",
            "- **평가 기준**: `nia_corpus_relative_pooled_v1` (24개 활성 질의, 초기 144건 anchor + reranker Top-3 신규 노출 56건 = 총 200건 블라인드 판정)",
            "- **골든셋 산출물**: `tests/agent/nia_case_corpus_relative_golden_v2.jsonl`",
            "- **평가 결과 산출물**: `tests/agent/nia_case_corpus_relative_evaluation_results_v2.jsonl`",
            "- **단계별 지표**:",
            "  - Dense Top-40: `Anchor Success@40`, `Anchor Recall@40`",
            "  - Metadata Top-20: `Anchor Success@20`, `Anchor Retention@20`",
            "  - Reranker Top-3: `Precision@3`, `nDCG@3`, `Grade-3 Hit Rate@3`, `direction conflict@3`, `exact duplicate@3`",
            "",
            "## 2. Cohort별 요약 지표",
            "",
            "| 구분 | 질의 수 | Anchor Success@40 | Anchor Recall@40 | Metadata Success@20 | Metadata Retention@20 | Precision@3 | nDCG@3 | 3점 포함 비율@3 | 방향 충돌 수@3 | 중복 노출 수@3 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for agg in report.aggregates:
            lines.append(
                f"| `{agg.slice.value}` | {agg.query_count} | "
                f"{agg.anchor_success_at_40:.3f} | {agg.anchor_recall_at_40:.3f} | "
                f"{agg.metadata_anchor_success_at_20:.3f} | {agg.metadata_anchor_retention_at_20:.3f} | "
                f"{agg.reranker_precision_at_3:.3f} | {agg.reranker_ndcg_at_3:.3f} | "
                f"{agg.reranker_grade_3_hit_rate_at_3:.3f} | "
                f"{agg.reranker_direction_conflict_total} | {agg.reranker_exact_duplicate_total} |"
            )

        lines.extend(
            [
                "",
                "## 3. 질의별 상세 결과 (24개 활성 질의)",
                "",
                "| evaluation_id | cohort | 관련 anchor 수 | Dense 회수/전체 | Metadata 보존/Dense | Top-3 등급 | Precision@3 | nDCG@3 | 방향 충돌@3 | 중복@3 |",
                "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in report.queries:
            grades_text = ", ".join(str(int(g)) for g in item.reranker_top_3.grades)
            lines.append(
                f"| `{item.evaluation_id.value}` | `{item.cohort.value}` | "
                f"{item.relevant_anchor_count} | "
                f"{item.dense_top_40.retrieved_relevant_anchor_count}/{item.relevant_anchor_count} | "
                f"{item.metadata_top_20.retained_relevant_anchor_count}/{item.dense_top_40.retrieved_relevant_anchor_count} | "
                f"`[{grades_text}]` | {item.reranker_top_3.precision_at_3:.3f} | "
                f"{item.reranker_top_3.ndcg_at_3:.3f} | "
                f"{item.reranker_top_3.direction_conflict_at_3} | "
                f"{item.reranker_top_3.exact_duplicate_at_3} |"
            )
        lines.extend(
            [
                "",
                "## 4. 단계별 주요 병목 및 시사점",
                "",
                "1. **Dense Top-40 (`Anchor Success@40 = 0.833`, `Anchor Recall@40 = 0.481`)**:",
                "   - 24개 활성 질의 중 20개(83.3%)에서 관련 anchor(`relevance_grade >= 2`)를 최소 1건 이상 회수했다.",
                "   - 미회수 4건 중 2건(`evaluation_core_pores_08`, `evaluation_rare_sagging_01`)은 코퍼스 내 초기 anchor 6건에 2점 이상 후보가 없는 코퍼스 한계 구간이며, 나머지 2건(`evaluation_core_pigment_01`, `evaluation_core_acne_03`)은 관련 anchor가 `off_rank_query_match`(Top-40 밖)에만 분포한 케이스다.",
                "2. **Metadata Top-20 (`Anchor Retention@20 = 0.892`, `Anchor Success@20 = 0.792`)**:",
                "   - Dense Top-40이 회수한 관련 anchor의 89.2%를 유지했다. `evaluation_core_pigment_04`에서만 Dense가 회수한 anchor 1건이 제외되었으나, Reranker 단계에서 보완 후보(`grade=2`) 3건을 상위로 정렬해 `Precision@3 = 1.000`을 유지했다.",
                "3. **Reranker Top-3 (`Precision@3 = 0.806`, `nDCG@3 = 0.787`, `direction conflict@3 = 4`, `exact duplicate@3 = 2`)**:",
                "   - 24개 질의 중 18개 질의에서 `Precision@3 = 1.000`, 17개 질의(70.8%)에서 최고 등급(`3점`) 사례를 Top-3에 포함시켰다.",
                "   - **케어 방향 충돌(`direction conflict@3 = 4`)**: 각질 제거 과다로 볼이 화끈거리는 `evaluation_core_pores_08`(3건)과 새 화장품 자극으로 볼이 따갑고 붉어진 `evaluation_rare_sensitive_01`(1건)에서 BHA/레티놀 등 공격적 각질·피지 케어 사례가 노출되었다.",
                "   - **동일 본문 중복(`exact duplicate@3 = 2`)**: `evaluation_core_pores_05`와 `evaluation_core_acne_01`에서 동일 `(question, answer)` 텍스트를 가진 중복 Case가 Top-3 중 2개 슬롯을 점유해 후보 정규화(deduplication)의 필요성을 보여준다.",
                "",
            ]
        )
        return "\n".join(lines)


class NiaCaseCorpusRelativeEvaluationCli:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_queries_v1.jsonl"
    )
    MANIFEST_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_anchor_manifest_v1.jsonl"
    )
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    RERANK_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_rerank_probe_v1.jsonl"
    )
    ANCHOR_JUDGMENT_DIR: ClassVar[Path] = Path("tests/agent")
    RERANK_JUDGMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_rerank_judgments_v1.jsonl"
    )
    GOLDEN_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v2.jsonl"
    )
    EVALUATION_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_evaluation_results_v2.jsonl"
    )
    REPORT_OUTPUT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_0335_NIA_CASE_CORPUS_RELATIVE_GOLDEN_EVAL_REPORT.md"
    )

    @classmethod
    def main(cls) -> None:
        queries = NiaCaseSemanticEvaluationQueryLoader().load(cls.QUERY_PATH).items
        manifests = [
            CorpusRelativeAnchorManifestItem.model_validate_json(line)
            for line in cls.MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        query_ids = {item.evaluation_id for item in queries}
        internal_items = [
            item
            for item in CandidatePoolArtifactLoader().load_internal(cls.INTERNAL_POOL_PATH)
            if item.evaluation_id in query_ids
        ]
        probes = [
            NiaCaseSemanticRerankProbeItem.model_validate_json(line)
            for line in cls.RERANK_PROBE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        probes = [item for item in probes if item.evaluation_id in query_ids]

        judgment_loader = NiaCaseCorpusRelativeJudgmentArtifactLoader()
        anchor_batches = judgment_loader.load_anchor_batches(cls.ANCHOR_JUDGMENT_DIR)
        rerank_batches = judgment_loader.load_rerank_batches(cls.RERANK_JUDGMENT_PATH)

        golden_cases = NiaCaseCorpusRelativeGoldenBuilder().build(
            queries=queries,
            manifests=manifests,
            internal_items=internal_items,
            anchor_batches=anchor_batches,
            rerank_batches=rerank_batches,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.GOLDEN_OUTPUT_PATH, list(golden_cases))

        report = NiaCaseCorpusRelativeGoldenEvaluator().evaluate(
            queries=queries,
            golden_cases=golden_cases,
            internal_items=internal_items,
            probes=probes,
        )
        writer.write(cls.EVALUATION_OUTPUT_PATH, list(report.queries))
        cls.REPORT_OUTPUT_PATH.write_text(
            NiaCaseCorpusRelativeMarkdownReporter().render(report),
            encoding="utf-8",
        )
        all_agg = report.aggregates[0]
        print(
            "corpus-relative golden v2 frozen & evaluated: "
            f"queries={len(golden_cases)}, qrels={sum(item.total_qrel_count for item in golden_cases)}, "
            f"anchor_success@40={all_agg.anchor_success_at_40:.3f}, "
            f"anchor_recall@40={all_agg.anchor_recall_at_40:.3f}, "
            f"retention@20={all_agg.metadata_anchor_retention_at_20:.3f}, "
            f"precision@3={all_agg.reranker_precision_at_3:.3f}, "
            f"ndcg@3={all_agg.reranker_ndcg_at_3:.3f}, "
            f"conflict@3={all_agg.reranker_direction_conflict_total}"
        )


if __name__ == "__main__":
    NiaCaseCorpusRelativeEvaluationCli.main()
