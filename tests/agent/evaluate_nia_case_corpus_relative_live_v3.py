"""현재 로컬 모델과 DB로 NIA Case 골든셋 v3 성능을 다시 측정한다."""

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import Field, FiniteFloat

from agent.rag.case_schemas import (
    DEFAULT_CASE_CANDIDATE_LIMIT,
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseRerankRequest,
    CaseSearchHit,
)
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.retrieval.case_candidate_selector import (
    CaseCandidateSelectionRequest,
    CaseMetadataCandidateSelector,
)
from agent.rag.retrieval.case_reranker import LocalBgeCaseRerankerV2M3
from agent.rag.retrieval.cross_encoder import LocalBgeCrossEncoderScorer
from agent.rag.schemas import RagModel
from backend.services.two_layer_rag_adapters import BackendNiaCaseRetriever
from core.database import Database
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    CorpusRelativeEvaluationSlice,
    NiaCaseCorpusRelativeAggregate,
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeEvaluationReport,
    NiaCaseCorpusRelativeGoldenCase,
    NiaCaseCorpusRelativeGoldenEvaluator,
)
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    TwoLayerAgentModelConfigFactory,
    Utf8ConsoleConfigurator,
)
from tests.agent.nia_case_corpus_relevance_schemas import CorpusRelevanceGrade
from tests.agent.nia_case_semantic_candidate_pool import (
    BlindCandidatePoolEntry,
    BlindCandidatePoolItem,
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
    InternalCandidatePoolEntry,
    InternalCandidatePoolItem,
    NiaCaseSemanticCandidatePoolBuilder,
    NiaSemanticCorpusLoader,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
)
from tests.agent.nia_case_semantic_golden_schemas import (
    NiaCaseSemanticReferenceLoader,
    NiaCaseSemanticReferenceSet,
)
from tests.agent.nia_case_semantic_rerank_probe import (
    NiaCaseSemanticRerankProbeItem,
)


class CorpusRelativeLiveEvaluationStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_JUDGMENT = "needs_judgment"


class NiaCaseCorpusRelativeLiveProbeHit(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    case_id: str = Field(min_length=1)
    dense_rank: int = Field(ge=1, le=DEFAULT_CASE_CANDIDATE_LIMIT)
    metadata_rank: int = Field(ge=1)
    rerank_rank: int = Field(ge=1, le=3)
    rerank_score: FiniteFloat
    relevance_grade: CorpusRelevanceGrade | None = None


class NiaCaseCorpusRelativeLiveProbeItem(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    query: str = Field(min_length=1)
    direct_match_count: int = Field(ge=0)
    metadata_candidate_count: int = Field(ge=1)
    hits: list[NiaCaseCorpusRelativeLiveProbeHit] = Field(
        default_factory=list,
        max_length=3,
    )


class NiaCaseCorpusRelativeLiveProbeResult(RagModel):
    items: list[NiaCaseCorpusRelativeLiveProbeItem] = Field(min_length=1)
    unjudged_items: list[BlindCandidatePoolItem]


class NiaCaseCorpusRelativeLiveRunSummary(RagModel):
    run_id: str = Field(min_length=1)
    golden_version: str = Field(pattern=r"^v[0-9]+$")
    status: CorpusRelativeLiveEvaluationStatus
    query_count: int = Field(ge=1)
    corpus_case_count: int = Field(ge=1)
    dense_model: str = Field(min_length=1)
    reranker_model: str = Field(min_length=1)
    candidate_count: int = Field(ge=1)
    top3_count: int = Field(ge=1)
    unjudged_count: int = Field(ge=0)


class NiaCaseCorpusRelativeLiveProbe:
    """현재 selector와 reranker로 live Dense Top-40을 재정렬한다."""

    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"
    PROVENANCE_ARCHIVE: ClassVar[str] = "corpus_relative_live_v3"

    def __init__(self) -> None:
        reranker_config = TwoLayerAgentModelConfigFactory().create_reranker()
        scorer = LocalBgeCrossEncoderScorer(reranker_config)
        self._reranker = LocalBgeCaseRerankerV2M3(
            reranker_config,
            scorer=scorer,
        )
        self._selector = CaseMetadataCandidateSelector()

    async def run(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        internal_items: list[InternalCandidatePoolItem],
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase],
    ) -> NiaCaseCorpusRelativeLiveProbeResult:
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        golden_by_id = {item.evaluation_id.value: item for item in golden_cases}
        self._validate_id_set("live 후보 풀", queries, set(internal_by_id))
        self._validate_id_set("golden v3", queries, set(golden_by_id))

        items: list[NiaCaseCorpusRelativeLiveProbeItem] = []
        unjudged_items: list[BlindCandidatePoolItem] = []
        for query in queries:
            item, unjudged = await self._run_query(
                query,
                internal_by_id[query.evaluation_id],
                golden_by_id[query.evaluation_id],
            )
            items.append(item)
            if unjudged is not None:
                unjudged_items.append(unjudged)
            print(
                f"{query.evaluation_id}: top3={len(item.hits)}, "
                f"unjudged={0 if unjudged is None else unjudged.candidate_count}"
            )
        return NiaCaseCorpusRelativeLiveProbeResult(
            items=items,
            unjudged_items=unjudged_items,
        )

    async def _run_query(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        internal: InternalCandidatePoolItem,
        golden: NiaCaseCorpusRelativeGoldenCase,
    ) -> tuple[
        NiaCaseCorpusRelativeLiveProbeItem,
        BlindCandidatePoolItem | None,
    ]:
        dense = sorted(
            [
                item
                for item in internal.candidates
                if item.dense_rank is not None
                and item.dense_rank <= DEFAULT_CASE_CANDIDATE_LIMIT
            ],
            key=lambda item: (
                item.dense_rank or DEFAULT_CASE_CANDIDATE_LIMIT,
                item.case_id,
            ),
        )
        search_hits = [self._to_search_hit(item) for item in dense]
        selection = self._selector.select(
            CaseCandidateSelectionRequest(
                query=query.query,
                skin_concerns=[
                    concern.value
                    for concern in [
                        *query.primary_concerns,
                        *query.secondary_concerns,
                    ]
                ],
                candidates=search_hits,
            )
        )
        reranked = await self._reranker.rerank(
            CaseRerankRequest(
                query=query.query,
                candidates=selection.candidates,
            )
        )
        internal_by_id = {item.case_id: item for item in dense}
        metadata_ranks = {
            item.case_id: rank
            for rank, item in enumerate(selection.candidates, start=1)
        }
        grades_by_id = {
            item.case_id: item.relevance_grade for item in golden.graded_qrels
        }
        hits = [
            NiaCaseCorpusRelativeLiveProbeHit(
                review_key=internal_by_id[hit.case_id].review_key,
                case_id=hit.case_id,
                dense_rank=internal_by_id[hit.case_id].dense_rank or 1,
                metadata_rank=metadata_ranks[hit.case_id],
                rerank_rank=rank,
                rerank_score=hit.rerank_score or 0.0,
                relevance_grade=grades_by_id.get(hit.case_id),
            )
            for rank, hit in enumerate(reranked.hits, start=1)
        ]
        missing_candidates = [
            self._to_blind_entry(internal_by_id[hit.case_id])
            for hit in hits
            if hit.relevance_grade is None
        ]
        unjudged = (
            BlindCandidatePoolItem(
                evaluation_id=query.evaluation_id,
                query=query.query,
                candidate_count=len(missing_candidates),
                candidates=missing_candidates,
            )
            if missing_candidates
            else None
        )
        return (
            NiaCaseCorpusRelativeLiveProbeItem(
                evaluation_id=query.evaluation_id,
                query=query.query,
                direct_match_count=selection.direct_match_count,
                metadata_candidate_count=len(selection.candidates),
                hits=hits,
            ),
            unjudged,
        )

    def _to_search_hit(self, item: InternalCandidatePoolEntry) -> CaseSearchHit:
        if item.dense_similarity is None:
            raise RuntimeError(f"dense 후보 similarity가 없습니다: {item.case_id}")
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

    def _to_blind_entry(
        self,
        item: InternalCandidatePoolEntry,
    ) -> BlindCandidatePoolEntry:
        return BlindCandidatePoolEntry(
            review_key=item.review_key,
            gender=item.gender,
            age=item.age,
            skin_type=item.skin_type,
            question=item.question,
            answer=item.answer,
        )

    def _validate_id_set(
        self,
        label: str,
        queries: list[NiaCaseSemanticEvaluationQuery],
        actual_ids: set[str],
    ) -> None:
        expected_ids = {item.evaluation_id for item in queries}
        if actual_ids != expected_ids:
            raise RuntimeError(
                f"{label}의 evaluation_id가 활성 24질의와 다릅니다: "
                f"missing={sorted(expected_ids - actual_ids)}, "
                f"unexpected={sorted(actual_ids - expected_ids)}"
            )


class NiaCaseCorpusRelativeLiveMarkdownReporter:
    def render(
        self,
        summary: NiaCaseCorpusRelativeLiveRunSummary,
        baseline: NiaCaseCorpusRelativeEvaluationReport | None,
        live: NiaCaseCorpusRelativeEvaluationReport | None,
    ) -> str:
        lines = [
            f"# NIA Case 코퍼스 상대 골든셋 {summary.golden_version} Live 성능 평가",
            "",
            "## 실행 정보",
            "",
            f"- 실행 ID: `{summary.run_id}`",
            f"- 상태: `{summary.status.value}`",
            f"- 질의: {summary.query_count}건",
            f"- 코퍼스: {summary.corpus_case_count}건",
            f"- Dense 모델: `{summary.dense_model}`",
            f"- Reranker 모델: `{summary.reranker_model}`",
            f"- 전체 후보: {summary.candidate_count}건",
            f"- Top-3 결과: {summary.top3_count}건",
            f"- 미판정 Top-3: {summary.unjudged_count}건",
            "",
        ]
        if summary.status is CorpusRelativeLiveEvaluationStatus.NEEDS_JUDGMENT:
            lines.extend(
                [
                    "## 판정 보류",
                    "",
                    (
                        "새 Top-3 후보가 골든셋 v3에 없어 성능 수치를 계산하지 않았다. "
                        "블라인드 판정 후 qrel을 추가해야 한다."
                    ),
                    "",
                ]
            )
            return "\n".join(lines)
        if baseline is None or live is None:
            raise RuntimeError("완료 상태에는 baseline과 live 평가 결과가 필요합니다.")

        baseline_by_slice = {item.slice: item for item in baseline.aggregates}
        live_by_slice = {item.slice: item for item in live.aggregates}
        lines.extend(
            [
                "## 기준선 대비 결과",
                "",
                "| 구분 | 지표 | 기준선 | Live | 변화 |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for slice_name in CorpusRelativeEvaluationSlice:
            lines.extend(
                self._metric_lines(
                    slice_name,
                    baseline_by_slice[slice_name],
                    live_by_slice[slice_name],
                )
            )
        baseline_queries = {item.evaluation_id: item for item in baseline.queries}
        changed_top3 = [
            item.evaluation_id.value
            for item in live.queries
            if item.reranker_top_3.case_ids
            != baseline_queries[item.evaluation_id].reranker_top_3.case_ids
        ]
        lines.extend(
            [
                "",
                "## Top-3 구성이 달라진 질의",
                "",
                *(
                    [f"- `{evaluation_id}`" for evaluation_id in changed_top3]
                    if changed_top3
                    else ["- 없음"]
                ),
                "",
                "## 해석 주의",
                "",
                (
                    "Anchor Recall@40은 전체 3,581건의 완전 recall이 아니라 판정된 초기 anchor에 대한 회수율이다. "
                    "반면 Precision@3과 nDCG@3는 이번 실행 Top-3가 모두 판정된 경우에만 보고한다."
                ),
                "",
            ]
        )
        return "\n".join(lines)

    def _metric_lines(
        self,
        slice_name: CorpusRelativeEvaluationSlice,
        baseline: NiaCaseCorpusRelativeAggregate,
        live: NiaCaseCorpusRelativeAggregate,
    ) -> list[str]:
        metrics = [
            ("Anchor Success@40", baseline.anchor_success_at_40, live.anchor_success_at_40),
            ("Anchor Recall@40", baseline.anchor_recall_at_40, live.anchor_recall_at_40),
            (
                "Metadata Success@20",
                baseline.metadata_anchor_success_at_20,
                live.metadata_anchor_success_at_20,
            ),
            (
                "Metadata Retention@20",
                baseline.metadata_anchor_retention_at_20,
                live.metadata_anchor_retention_at_20,
            ),
            ("Precision@3", baseline.reranker_precision_at_3, live.reranker_precision_at_3),
            ("nDCG@3", baseline.reranker_ndcg_at_3, live.reranker_ndcg_at_3),
        ]
        return [
            f"| `{slice_name.value}` | {name} | {before:.3f} | {after:.3f} | "
            f"{after - before:+.3f} |"
            for name, before, after in metrics
        ]


class NiaCaseCorpusRelativeLiveV3Cli:
    RUN_ID: ClassVar[str] = "live_20260926_1416_v1"
    REFERENCE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_references_v1.jsonl"
    )
    CORPUS_PATH: ClassVar[Path] = Path(
        "data/processed/nia_case_documents_10s_30s.jsonl"
    )
    GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v3.jsonl"
    )
    BASELINE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    BASELINE_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_rerank_probe_v1.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )
    LIVE_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_probe_20260926_1416_v1.jsonl"
    )
    LIVE_UNJUDGED_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_unjudged_20260926_1416_v1.jsonl"
    )
    LIVE_RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_results_20260926_1416_v1.jsonl"
    )
    LIVE_SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_summary_20260926_1416_v1.jsonl"
    )
    LIVE_REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_1416_NIA_CASE_CORPUS_RELATIVE_LIVE_V3_REPORT.md"
    )

    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        paths = NiaCaseCorpusRelativeEvaluationCli
        queries = NiaCaseSemanticEvaluationQueryLoader().load(paths.QUERY_PATH).items
        query_ids = {item.evaluation_id for item in queries}
        references = [
            item
            for item in NiaCaseSemanticReferenceLoader().load(
                cls.REFERENCE_PATH
            ).items
            if item.evaluation_id in query_ids
        ]
        if {item.evaluation_id for item in references} != query_ids:
            raise RuntimeError("활성 24질의에 대응하는 추천 기준 카드가 부족합니다.")
        golden_cases = cls._load_golden(cls.GOLDEN_PATH)
        corpus = NiaSemanticCorpusLoader().load(cls.CORPUS_PATH)
        config = TwoLayerAgentModelConfigFactory()
        database: Database = ConfiguredDatabaseFactory().create()
        try:
            pool = await NiaCaseSemanticCandidatePoolBuilder(
                embedder=TextEmbedderFactory().create(config.create_embedding()),
                retriever=BackendNiaCaseRetriever(database.session_factory),
            ).build(
                NiaCaseSemanticReferenceSet(items=references),
                corpus,
            )
        finally:
            await database.dispose()

        writer = CandidatePoolJsonlWriter()
        writer.write(cls.LIVE_POOL_PATH, list(pool.internal_items))
        probe = await NiaCaseCorpusRelativeLiveProbe().run(
            queries,
            pool.internal_items,
            golden_cases,
        )
        writer.write(cls.LIVE_PROBE_PATH, list(probe.items))
        writer.write(cls.LIVE_UNJUDGED_PATH, list(probe.unjudged_items))

        unjudged_count = sum(
            item.candidate_count for item in probe.unjudged_items
        )
        status = (
            CorpusRelativeLiveEvaluationStatus.COMPLETE
            if unjudged_count == 0
            else CorpusRelativeLiveEvaluationStatus.NEEDS_JUDGMENT
        )
        summary = NiaCaseCorpusRelativeLiveRunSummary(
            run_id=cls.RUN_ID,
            golden_version="v3",
            status=status,
            query_count=len(queries),
            corpus_case_count=len(corpus.cases),
            dense_model="BAAI/bge-m3",
            reranker_model="BAAI/bge-reranker-v2-m3",
            candidate_count=sum(
                item.candidate_count for item in pool.internal_items
            ),
            top3_count=sum(len(item.hits) for item in probe.items),
            unjudged_count=unjudged_count,
        )
        writer.write(cls.LIVE_SUMMARY_PATH, [summary])

        baseline_report: NiaCaseCorpusRelativeEvaluationReport | None = None
        live_report: NiaCaseCorpusRelativeEvaluationReport | None = None
        if status is CorpusRelativeLiveEvaluationStatus.COMPLETE:
            evaluator = NiaCaseCorpusRelativeGoldenEvaluator()
            baseline_internal = [
                item
                for item in CandidatePoolArtifactLoader().load_internal(
                    cls.BASELINE_POOL_PATH
                )
                if item.evaluation_id in query_ids
            ]
            baseline_probes = [
                NiaCaseSemanticRerankProbeItem.model_validate_json(line)
                for line in cls.BASELINE_PROBE_PATH.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip() and cls._line_evaluation_id(line) in query_ids
            ]
            baseline_report = evaluator.evaluate(
                queries,
                golden_cases,
                baseline_internal,
                baseline_probes,
            )
            live_report = evaluator.evaluate(
                queries,
                golden_cases,
                pool.internal_items,
                probe.items,
            )
            writer.write(cls.LIVE_RESULT_PATH, list(live_report.queries))

        cls.LIVE_REPORT_PATH.write_text(
            NiaCaseCorpusRelativeLiveMarkdownReporter().render(
                summary,
                baseline_report,
                live_report,
            ),
            encoding="utf-8",
        )
        print(
            "live v3 평가 실행 완료: "
            f"status={summary.status.value}, queries={summary.query_count}, "
            f"candidates={summary.candidate_count}, "
            f"unjudged={summary.unjudged_count}"
        )

    @classmethod
    def _load_golden(cls, path: Path) -> list[NiaCaseCorpusRelativeGoldenCase]:
        return [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @classmethod
    def _line_evaluation_id(cls, line: str) -> str:
        return NiaCaseSemanticRerankProbeItem.model_validate_json(line).evaluation_id


if __name__ == "__main__":
    asyncio.run(NiaCaseCorpusRelativeLiveV3Cli.main())
