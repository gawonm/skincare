"""블라인드 감사 불일치를 조정하여 NIA Case 골든셋 v3를 만든다."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import Field

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    CorpusRelativeEvaluationSlice,
    NiaCaseCorpusRelativeAggregate,
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeEvaluationReport,
    NiaCaseCorpusRelativeGoldenCase,
    NiaCaseCorpusRelativeGoldenEvaluator,
    NiaCaseCorpusRelativeGradedQrel,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    CorpusRelevanceGrade,
    NiaCaseCorpusRelevanceJudgment,
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
)
from tests.agent.nia_case_semantic_rerank_probe import (
    NiaCaseSemanticRerankProbeItem,
)

AdjudicationModel = TypeVar("AdjudicationModel", bound=RagModel)


class CorpusRelativeAdjudicationDisposition(StrEnum):
    KEEP_FROZEN = "keep_frozen"
    ACCEPT_AUDIT = "accept_audit"


class NiaCaseCorpusRelativeAdjudication(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    disposition: CorpusRelativeAdjudicationDisposition
    final_judgment: NiaCaseCorpusRelevanceJudgment
    rationale: str = Field(min_length=10)


class NiaCaseCorpusRelativeAdjudicationResult(RagModel):
    golden_cases: list[NiaCaseCorpusRelativeGoldenCase] = Field(min_length=1)
    reviewed_count: int = Field(ge=1)
    changed_count: int = Field(ge=0)


class NiaCaseCorpusRelativeGoldenAdjudicator:
    """v2와 감사 판정을 검증한 뒤 명시된 최종 판정만 v3에 반영한다."""

    def apply(
        self,
        frozen_cases: list[NiaCaseCorpusRelativeGoldenCase],
        audit_batches: list[NiaCaseCorpusRelevanceJudgmentBatch],
        adjudications: list[NiaCaseCorpusRelativeAdjudication],
    ) -> NiaCaseCorpusRelativeAdjudicationResult:
        audit_by_key = {
            (batch.evaluation_id, judgment.review_key): judgment
            for batch in audit_batches
            for judgment in batch.judgments
        }
        adjudication_by_key = {
            (item.evaluation_id, item.review_key): item for item in adjudications
        }
        if len(adjudication_by_key) != len(adjudications):
            raise RuntimeError("중복된 골든셋 조정 항목이 있습니다.")

        reviewed_count = 0
        changed_count = 0
        rebuilt_cases: list[NiaCaseCorpusRelativeGoldenCase] = []
        for frozen_case in frozen_cases:
            rebuilt_qrels: list[NiaCaseCorpusRelativeGradedQrel] = []
            for qrel in frozen_case.graded_qrels:
                key = (frozen_case.evaluation_id.value, qrel.review_key)
                adjudication = adjudication_by_key.get(key)
                if adjudication is None:
                    rebuilt_qrels.append(qrel)
                    continue
                reviewed_count += 1
                frozen_judgment = self._to_judgment(qrel)
                audit_judgment = audit_by_key.get(key)
                if audit_judgment is None:
                    raise RuntimeError(f"감사 판정에서 조정 대상을 찾지 못했습니다: {key}")
                self._validate_disposition(
                    adjudication,
                    frozen_judgment,
                    audit_judgment,
                )
                rebuilt_qrel = self._replace_judgment(
                    qrel,
                    adjudication.final_judgment,
                )
                rebuilt_qrels.append(rebuilt_qrel)
                if rebuilt_qrel != qrel:
                    changed_count += 1
            rebuilt_cases.append(self._rebuild_case(frozen_case, rebuilt_qrels))

        if reviewed_count != len(adjudications):
            raise RuntimeError(
                "골든셋에서 일부 조정 대상을 찾지 못했습니다: "
                f"expected={len(adjudications)}, actual={reviewed_count}"
            )
        return NiaCaseCorpusRelativeAdjudicationResult(
            golden_cases=rebuilt_cases,
            reviewed_count=reviewed_count,
            changed_count=changed_count,
        )

    def _validate_disposition(
        self,
        adjudication: NiaCaseCorpusRelativeAdjudication,
        frozen: NiaCaseCorpusRelevanceJudgment,
        audit: NiaCaseCorpusRelevanceJudgment,
    ) -> None:
        expected = (
            frozen
            if adjudication.disposition
            is CorpusRelativeAdjudicationDisposition.KEEP_FROZEN
            else audit
        )
        if adjudication.final_judgment != expected:
            raise RuntimeError(
                "조정 결정과 최종 판정 내용이 일치하지 않습니다: "
                f"{adjudication.evaluation_id}/{adjudication.review_key}"
            )

    def _to_judgment(
        self,
        qrel: NiaCaseCorpusRelativeGradedQrel,
    ) -> NiaCaseCorpusRelevanceJudgment:
        return NiaCaseCorpusRelevanceJudgment.model_validate(
            qrel.model_dump(
                include={
                    "review_key",
                    "concern_fit",
                    "context_fit",
                    "request_fit",
                    "direction_conflicts",
                    "reason_codes",
                    "relevance_grade",
                    "note",
                }
            )
        )

    def _replace_judgment(
        self,
        qrel: NiaCaseCorpusRelativeGradedQrel,
        judgment: NiaCaseCorpusRelevanceJudgment,
    ) -> NiaCaseCorpusRelativeGradedQrel:
        payload = qrel.model_dump()
        payload.update(judgment.model_dump())
        return NiaCaseCorpusRelativeGradedQrel.model_validate(payload)

    def _rebuild_case(
        self,
        frozen: NiaCaseCorpusRelativeGoldenCase,
        qrels: list[NiaCaseCorpusRelativeGradedQrel],
    ) -> NiaCaseCorpusRelativeGoldenCase:
        relevant_case_ids = sorted(
            qrel.case_id
            for qrel in qrels
            if qrel.is_initial_anchor
            and qrel.relevance_grade >= CorpusRelevanceGrade.RELEVANT
        )
        return NiaCaseCorpusRelativeGoldenCase(
            evaluation_id=frozen.evaluation_id,
            cohort=frozen.cohort,
            policy=frozen.policy,
            query=frozen.query,
            relevant_case_ids=relevant_case_ids,
            anchor_qrel_count=frozen.anchor_qrel_count,
            total_qrel_count=frozen.total_qrel_count,
            graded_qrels=qrels,
        )


class NiaCaseCorpusRelativeAdjudicationMarkdownReporter:
    """v2 보존과 v3 변경 내용을 함께 볼 수 있는 조정 보고서를 만든다."""

    def render(
        self,
        adjudications: list[NiaCaseCorpusRelativeAdjudication],
        frozen_report: NiaCaseCorpusRelativeEvaluationReport,
        adjudicated_report: NiaCaseCorpusRelativeEvaluationReport,
    ) -> str:
        frozen_aggregates = {item.slice: item for item in frozen_report.aggregates}
        adjudicated_aggregates = {
            item.slice: item for item in adjudicated_report.aggregates
        }
        lines = [
            "# NIA Case 코퍼스 상대 골든셋 v3 조정 보고서",
            "",
            "## 결론",
            "",
            "- v2 원본은 변경하지 않고 24건 블라인드 감사에서 불일치한 9건만 재검토했다.",
            "- 4건은 v2 판정을 유지하고 5건은 감사 판정을 채택했다.",
            "- 임베딩·검색·리랭킹을 다시 실행하지 않고 기존 고정 후보와 순위에 조정 qrel만 적용했다.",
            "",
            "## 조정 내역",
            "",
            "| evaluation_id | review_key | 결정 | 최종 등급 | 근거 |",
            "| --- | --- | --- | ---: | --- |",
        ]
        for item in adjudications:
            lines.append(
                f"| `{item.evaluation_id}` | `{item.review_key}` | "
                f"`{item.disposition.value}` | "
                f"{int(item.final_judgment.relevance_grade)} | {item.rationale} |"
            )
        lines.extend(
            [
                "",
                "## v2 → v3 지표 변화",
                "",
                "| 구분 | 지표 | v2 | v3 | 변화 |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for slice_name in CorpusRelativeEvaluationSlice:
            frozen = frozen_aggregates[slice_name]
            adjudicated = adjudicated_aggregates[slice_name]
            lines.extend(self._metric_lines(slice_name, frozen, adjudicated))

        changed_queries = [
            adjudicated
            for frozen, adjudicated in zip(
                frozen_report.queries,
                adjudicated_report.queries,
                strict=True,
            )
            if frozen != adjudicated
        ]
        lines.extend(
            [
                "",
                "## 평가 결과가 바뀐 질의",
                "",
                *[
                    f"- `{item.evaluation_id.value}`"
                    for item in changed_queries
                ],
                "",
                "## 해석",
                "",
                (
                    "v3는 복원 가능한 v2를 폐기한 새 골든셋이 아니라, 블라인드 감사 불일치만 명시적으로 "
                    "조정한 후속 버전이다. 특히 방향 충돌과 복합 질의의 부분 대응 여부를 더 엄격히 구분한다."
                ),
                "",
            ]
        )
        return "\n".join(lines)

    def _metric_lines(
        self,
        slice_name: CorpusRelativeEvaluationSlice,
        frozen: NiaCaseCorpusRelativeAggregate,
        adjudicated: NiaCaseCorpusRelativeAggregate,
    ) -> list[str]:
        metrics = [
            ("Anchor Success@40", frozen.anchor_success_at_40, adjudicated.anchor_success_at_40),
            ("Anchor Recall@40", frozen.anchor_recall_at_40, adjudicated.anchor_recall_at_40),
            (
                "Metadata Success@20",
                frozen.metadata_anchor_success_at_20,
                adjudicated.metadata_anchor_success_at_20,
            ),
            (
                "Metadata Retention@20",
                frozen.metadata_anchor_retention_at_20,
                adjudicated.metadata_anchor_retention_at_20,
            ),
            ("Precision@3", frozen.reranker_precision_at_3, adjudicated.reranker_precision_at_3),
            ("nDCG@3", frozen.reranker_ndcg_at_3, adjudicated.reranker_ndcg_at_3),
        ]
        return [
            f"| `{slice_name.value}` | {name} | {before:.3f} | {after:.3f} | "
            f"{after - before:+.3f} |"
            for name, before, after in metrics
        ]


class NiaCaseCorpusRelativeAdjudicationCli:
    AUDIT_JUDGMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_audit_judgments_v1.jsonl"
    )
    ADJUDICATION_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_adjudications_v1.jsonl"
    )
    GOLDEN_V3_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v3.jsonl"
    )
    EVALUATION_V3_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_evaluation_results_v3.jsonl"
    )
    REPORT_OUTPUT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_NIA_CASE_CORPUS_RELATIVE_GOLDEN_V3_ADJUDICATION_REPORT.md"
    )

    @classmethod
    def main(cls) -> None:
        paths = NiaCaseCorpusRelativeEvaluationCli
        frozen_cases = cls._load_models(
            paths.GOLDEN_OUTPUT_PATH,
            NiaCaseCorpusRelativeGoldenCase,
        )
        audit_batches = cls._load_models(
            cls.AUDIT_JUDGMENT_PATH,
            NiaCaseCorpusRelevanceJudgmentBatch,
        )
        adjudications = cls._load_models(
            cls.ADJUDICATION_PATH,
            NiaCaseCorpusRelativeAdjudication,
        )
        result = NiaCaseCorpusRelativeGoldenAdjudicator().apply(
            frozen_cases=frozen_cases,
            audit_batches=audit_batches,
            adjudications=adjudications,
        )

        queries = NiaCaseSemanticEvaluationQueryLoader().load(paths.QUERY_PATH).items
        query_ids = {item.evaluation_id for item in queries}
        internal_items = [
            item
            for item in CandidatePoolArtifactLoader().load_internal(
                paths.INTERNAL_POOL_PATH
            )
            if item.evaluation_id in query_ids
        ]
        probes = [
            item
            for item in cls._load_models(
                paths.RERANK_PROBE_PATH,
                NiaCaseSemanticRerankProbeItem,
            )
            if item.evaluation_id in query_ids
        ]
        evaluator = NiaCaseCorpusRelativeGoldenEvaluator()
        frozen_report = evaluator.evaluate(
            queries=queries,
            golden_cases=frozen_cases,
            internal_items=internal_items,
            probes=probes,
        )
        adjudicated_report = evaluator.evaluate(
            queries=queries,
            golden_cases=result.golden_cases,
            internal_items=internal_items,
            probes=probes,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.GOLDEN_V3_OUTPUT_PATH, list(result.golden_cases))
        writer.write(
            cls.EVALUATION_V3_OUTPUT_PATH,
            list(adjudicated_report.queries),
        )
        cls.REPORT_OUTPUT_PATH.write_text(
            NiaCaseCorpusRelativeAdjudicationMarkdownReporter().render(
                adjudications,
                frozen_report,
                adjudicated_report,
            ),
            encoding="utf-8",
        )
        aggregate = adjudicated_report.aggregates[0]
        print(
            "골든셋 v3 조정 완료: "
            f"reviewed={result.reviewed_count}, changed={result.changed_count}, "
            f"anchor_success@40={aggregate.anchor_success_at_40:.3f}, "
            f"anchor_recall@40={aggregate.anchor_recall_at_40:.3f}, "
            f"precision@3={aggregate.reranker_precision_at_3:.3f}, "
            f"ndcg@3={aggregate.reranker_ndcg_at_3:.3f}"
        )

    @classmethod
    def _load_models(
        cls,
        path: Path,
        model_type: type[AdjudicationModel],
    ) -> list[AdjudicationModel]:
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    NiaCaseCorpusRelativeAdjudicationCli.main()
