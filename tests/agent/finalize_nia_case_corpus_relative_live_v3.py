"""Live Top-3 보완 판정을 골든셋에 추가하고 성능 평가를 마무리한다."""

from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import Field

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeGoldenCase,
    NiaCaseCorpusRelativeGoldenEvaluator,
    NiaCaseCorpusRelativeGradedQrel,
)
from tests.agent.evaluate_nia_case_corpus_relative_live_v3 import (
    CorpusRelativeLiveEvaluationStatus,
    NiaCaseCorpusRelativeLiveMarkdownReporter,
    NiaCaseCorpusRelativeLiveProbeItem,
    NiaCaseCorpusRelativeLiveRunSummary,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    BlindCandidatePoolItem,
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
    InternalCandidatePoolItem,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
)
from tests.agent.nia_case_semantic_rerank_probe import (
    NiaCaseSemanticRerankProbeItem,
)

LiveFinalizerModel = TypeVar("LiveFinalizerModel", bound=RagModel)


class NiaCaseCorpusRelativeLiveExpansionResult(RagModel):
    golden_cases: list[NiaCaseCorpusRelativeGoldenCase] = Field(min_length=1)
    added_qrel_count: int = Field(ge=1)


class NiaCaseCorpusRelativeLiveGoldenExpander:
    """미판정 Top-3와 보완 판정이 정확히 일치할 때만 qrel을 확장한다."""

    def expand(
        self,
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase],
        internal_items: list[InternalCandidatePoolItem],
        unjudged_items: list[BlindCandidatePoolItem],
        supplement_batches: list[NiaCaseCorpusRelevanceJudgmentBatch],
    ) -> NiaCaseCorpusRelativeLiveExpansionResult:
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        supplement_by_id = {
            item.evaluation_id: item for item in supplement_batches
        }
        expected_keys = {
            (item.evaluation_id, candidate.review_key)
            for item in unjudged_items
            for candidate in item.candidates
        }
        actual_keys = {
            (batch.evaluation_id, judgment.review_key)
            for batch in supplement_batches
            for judgment in batch.judgments
        }
        if actual_keys != expected_keys:
            raise RuntimeError(
                "Live 보완 판정이 미판정 Top-3를 정확히 덮지 않습니다: "
                f"judgments_only={sorted(actual_keys - expected_keys)}, "
                f"unjudged_only={sorted(expected_keys - actual_keys)}"
            )

        expanded_cases: list[NiaCaseCorpusRelativeGoldenCase] = []
        added_count = 0
        for golden in golden_cases:
            batch = supplement_by_id.get(golden.evaluation_id.value)
            if batch is None:
                expanded_cases.append(golden)
                continue
            entries_by_key = {
                item.review_key: item
                for item in internal_by_id[golden.evaluation_id.value].candidates
            }
            existing_keys = {item.review_key for item in golden.graded_qrels}
            existing_case_ids = {item.case_id for item in golden.graded_qrels}
            additions: list[NiaCaseCorpusRelativeGradedQrel] = []
            for judgment in batch.judgments:
                if judgment.review_key in existing_keys:
                    raise RuntimeError(
                        "Live 보완 판정이 기존 qrel과 중복됩니다: "
                        f"{golden.evaluation_id.value}/{judgment.review_key}"
                    )
                entry = entries_by_key.get(judgment.review_key)
                if entry is None:
                    raise RuntimeError(
                        "Live 후보 풀에서 보완 판정 대상을 찾지 못했습니다: "
                        f"{golden.evaluation_id.value}/{judgment.review_key}"
                    )
                if entry.case_id in existing_case_ids:
                    raise RuntimeError(
                        "Live 보완 판정의 case_id가 기존 qrel과 중복됩니다: "
                        f"{golden.evaluation_id.value}/{entry.case_id}"
                    )
                additions.append(
                    NiaCaseCorpusRelativeGradedQrel(
                        case_id=entry.case_id,
                        review_key=judgment.review_key,
                        is_initial_anchor=False,
                        anchor_stratum=None,
                        relevance_grade=judgment.relevance_grade,
                        concern_fit=judgment.concern_fit,
                        context_fit=judgment.context_fit,
                        request_fit=judgment.request_fit,
                        direction_conflicts=judgment.direction_conflicts,
                        reason_codes=judgment.reason_codes,
                        note=judgment.note,
                    )
                )
            qrels = sorted(
                [*golden.graded_qrels, *additions],
                key=lambda item: item.review_key,
            )
            expanded_cases.append(
                NiaCaseCorpusRelativeGoldenCase(
                    evaluation_id=golden.evaluation_id,
                    cohort=golden.cohort,
                    policy=golden.policy,
                    query=golden.query,
                    relevant_case_ids=golden.relevant_case_ids,
                    anchor_qrel_count=golden.anchor_qrel_count,
                    total_qrel_count=len(qrels),
                    graded_qrels=qrels,
                )
            )
            added_count += len(additions)
        if added_count != len(actual_keys):
            raise RuntimeError(
                "일부 Live 보완 판정이 골든셋에 추가되지 않았습니다: "
                f"expected={len(actual_keys)}, actual={added_count}"
            )
        return NiaCaseCorpusRelativeLiveExpansionResult(
            golden_cases=expanded_cases,
            added_qrel_count=added_count,
        )


class NiaCaseCorpusRelativeLiveV3FinalizerCli:
    RUN_ID: ClassVar[str] = "live_20260926_1416_v1"
    EXPECTED_CORPUS_CASE_COUNT: ClassVar[int] = 3581
    GOLDEN_V3_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v3.jsonl"
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
    SUPPLEMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_supplement_judgments_20260926_1416_v1.jsonl"
    )
    GOLDEN_V4_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v4.jsonl"
    )
    EVALUATION_V4_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_evaluation_results_v4.jsonl"
    )
    LIVE_RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_results_20260926_1416_v1.jsonl"
    )
    LIVE_SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_final_summary_20260926_1416_v1.jsonl"
    )
    LIVE_REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_1416_NIA_CASE_CORPUS_RELATIVE_LIVE_V4_REPORT.md"
    )
    BASELINE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    BASELINE_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_rerank_probe_v1.jsonl"
    )

    @classmethod
    def main(cls) -> None:
        evaluation_paths = NiaCaseCorpusRelativeEvaluationCli
        queries = NiaCaseSemanticEvaluationQueryLoader().load(
            evaluation_paths.QUERY_PATH
        ).items
        query_ids = {item.evaluation_id for item in queries}
        live_internal = CandidatePoolArtifactLoader().load_internal(
            cls.LIVE_POOL_PATH
        )
        live_probes = cls._load_models(
            cls.LIVE_PROBE_PATH,
            NiaCaseCorpusRelativeLiveProbeItem,
        )
        expansion = NiaCaseCorpusRelativeLiveGoldenExpander().expand(
            golden_cases=cls._load_models(
                cls.GOLDEN_V3_PATH,
                NiaCaseCorpusRelativeGoldenCase,
            ),
            internal_items=live_internal,
            unjudged_items=CandidatePoolArtifactLoader().load_blind(
                cls.LIVE_UNJUDGED_PATH
            ),
            supplement_batches=cls._load_models(
                cls.SUPPLEMENT_PATH,
                NiaCaseCorpusRelevanceJudgmentBatch,
            ),
        )
        evaluator = NiaCaseCorpusRelativeGoldenEvaluator()
        live_report = evaluator.evaluate(
            queries,
            expansion.golden_cases,
            live_internal,
            live_probes,
        )
        baseline_report = evaluator.evaluate(
            queries,
            expansion.golden_cases,
            [
                item
                for item in CandidatePoolArtifactLoader().load_internal(
                    cls.BASELINE_POOL_PATH
                )
                if item.evaluation_id in query_ids
            ],
            [
                item
                for item in cls._load_models(
                    cls.BASELINE_PROBE_PATH,
                    NiaCaseSemanticRerankProbeItem,
                )
                if item.evaluation_id in query_ids
            ],
        )
        summary = NiaCaseCorpusRelativeLiveRunSummary(
            run_id=cls.RUN_ID,
            golden_version="v4",
            status=CorpusRelativeLiveEvaluationStatus.COMPLETE,
            query_count=len(queries),
            corpus_case_count=cls.EXPECTED_CORPUS_CASE_COUNT,
            dense_model="BAAI/bge-m3",
            reranker_model="BAAI/bge-reranker-v2-m3",
            candidate_count=sum(item.candidate_count for item in live_internal),
            top3_count=sum(len(item.hits) for item in live_probes),
            unjudged_count=0,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.GOLDEN_V4_OUTPUT_PATH, list(expansion.golden_cases))
        writer.write(cls.EVALUATION_V4_OUTPUT_PATH, list(live_report.queries))
        writer.write(cls.LIVE_RESULT_PATH, list(live_report.queries))
        writer.write(cls.LIVE_SUMMARY_PATH, [summary])
        cls.LIVE_REPORT_PATH.write_text(
            NiaCaseCorpusRelativeLiveMarkdownReporter().render(
                summary,
                baseline_report,
                live_report,
            ),
            encoding="utf-8",
        )
        aggregate = live_report.aggregates[0]
        print(
            "Live v3 보완 판정 및 v4 평가 완료: "
            f"added_qrels={expansion.added_qrel_count}, "
            f"anchor_success@40={aggregate.anchor_success_at_40:.3f}, "
            f"anchor_recall@40={aggregate.anchor_recall_at_40:.3f}, "
            f"precision@3={aggregate.reranker_precision_at_3:.3f}, "
            f"ndcg@3={aggregate.reranker_ndcg_at_3:.3f}"
        )

    @classmethod
    def _load_models(
        cls,
        path: Path,
        model_type: type[LiveFinalizerModel],
    ) -> list[LiveFinalizerModel]:
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    NiaCaseCorpusRelativeLiveV3FinalizerCli.main()
