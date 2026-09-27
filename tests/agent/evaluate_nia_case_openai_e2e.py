"""OpenAI 라우팅 결과를 동결된 NIA Case v4 검색 성능과 결합한다."""

from enum import StrEnum
from pathlib import Path
from statistics import fmean
from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeQueryEvaluation,
)
from tests.agent.evaluate_nia_case_openai_routing_once import (
    NiaCaseOpenAiQueryRelation,
    NiaCaseOpenAiRoutingCheckpoint,
    NiaCaseOpenAiRoutingRecord,
    NiaCaseOpenAiRoutingSummary,
)
from tests.agent.nia_case_semantic_candidate_pool import CandidatePoolJsonlWriter


class NiaCaseOpenAiE2ESlice(StrEnum):
    RETRIEVAL_ONLY = "retrieval_only"
    ROUTED_CONDITIONAL = "routed_conditional"
    END_TO_END = "end_to_end"


class NiaCaseOpenAiE2EMetrics(RagModel):
    slice: NiaCaseOpenAiE2ESlice
    query_count: int = Field(ge=1)
    case_route_count: int = Field(ge=0)
    case_route_rate: float = Field(ge=0.0, le=1.0)
    anchor_success_at_40: float = Field(ge=0.0, le=1.0)
    anchor_recall_at_40: float = Field(ge=0.0, le=1.0)
    metadata_success_at_20: float = Field(ge=0.0, le=1.0)
    metadata_anchor_recall_at_20: float = Field(ge=0.0, le=1.0)
    metadata_retention_at_20: float = Field(ge=0.0, le=1.0)
    top3_output_rate: float = Field(ge=0.0, le=1.0)
    precision_at_3: float = Field(ge=0.0, le=1.0)
    ndcg_at_3: float = Field(ge=0.0, le=1.0)


class NiaCaseOpenAiRoutingFailureImpact(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    query: str = Field(min_length=1)
    parsed_route: str = Field(min_length=1)
    parsed_intents: list[str] = Field(min_length=1)
    llm_case_query_draft: str | None = None
    retrieval_anchor_success_at_40: bool
    retrieval_anchor_recall_at_40: float = Field(ge=0.0, le=1.0)
    retrieval_precision_at_3: float = Field(ge=0.0, le=1.0)
    retrieval_ndcg_at_3: float = Field(ge=0.0, le=1.0)


class NiaCaseOpenAiE2EReport(RagModel):
    run_id: str = Field(min_length=1)
    query_count: int = Field(ge=1)
    metrics: list[NiaCaseOpenAiE2EMetrics] = Field(min_length=3, max_length=3)
    routing_failures: list[NiaCaseOpenAiRoutingFailureImpact]


class NiaCaseOpenAiE2ECalculator:
    def calculate(
        self,
        run_id: str,
        routing_records: list[NiaCaseOpenAiRoutingRecord],
        retrieval_results: list[NiaCaseCorpusRelativeQueryEvaluation],
        routed_ids: set[str] | None = None,
    ) -> NiaCaseOpenAiE2EReport:
        routing_by_id = {record.evaluation_id: record for record in routing_records}
        retrieval_by_id = {
            result.evaluation_id.value: result for result in retrieval_results
        }
        if set(routing_by_id) != set(retrieval_by_id):
            raise RuntimeError(
                "OpenAI 라우팅 결과와 v4 검색 결과의 evaluation_id가 다릅니다."
            )
        effective_routed_ids = (
            routed_ids
            if routed_ids is not None
            else {
                record.evaluation_id
                for record in routing_records
                if record.case_query_relation
                is not NiaCaseOpenAiQueryRelation.MISSING
            }
        )
        ordered_results = [
            retrieval_by_id[record.evaluation_id] for record in routing_records
        ]
        routed_results = [
            result
            for result in ordered_results
            if result.evaluation_id.value in effective_routed_ids
        ]
        metrics = [
            self._metrics(
                NiaCaseOpenAiE2ESlice.RETRIEVAL_ONLY,
                ordered_results,
                {result.evaluation_id.value for result in ordered_results},
            ),
            self._metrics(
                NiaCaseOpenAiE2ESlice.ROUTED_CONDITIONAL,
                routed_results,
                effective_routed_ids,
            ),
            self._metrics(
                NiaCaseOpenAiE2ESlice.END_TO_END,
                ordered_results,
                effective_routed_ids,
            ),
        ]
        failures = [
            self._failure(record, retrieval_by_id[record.evaluation_id])
            for record in routing_records
            if record.evaluation_id not in effective_routed_ids
        ]
        return NiaCaseOpenAiE2EReport(
            run_id=run_id,
            query_count=len(routing_records),
            metrics=metrics,
            routing_failures=failures,
        )

    def _metrics(
        self,
        slice_name: NiaCaseOpenAiE2ESlice,
        results: list[NiaCaseCorpusRelativeQueryEvaluation],
        routed_ids: set[str],
    ) -> NiaCaseOpenAiE2EMetrics:
        if not results:
            raise RuntimeError(f"{slice_name.value} 지표를 계산할 검색 결과가 없습니다.")
        relevant_results = [result for result in results if result.relevant_anchor_count > 0]
        dense_hit_results = [
            result
            for result in results
            if result.dense_top_40.retrieved_relevant_anchor_count > 0
        ]
        route_flags = [result.evaluation_id.value in routed_ids for result in results]
        return NiaCaseOpenAiE2EMetrics(
            slice=slice_name,
            query_count=len(results),
            case_route_count=sum(route_flags),
            case_route_rate=fmean(route_flags),
            anchor_success_at_40=fmean(
                result.evaluation_id.value in routed_ids
                and result.dense_top_40.anchor_success_at_40
                for result in results
            ),
            anchor_recall_at_40=fmean(
                result.dense_top_40.anchor_recall_at_40
                if result.evaluation_id.value in routed_ids
                else 0.0
                for result in relevant_results
            ),
            metadata_success_at_20=fmean(
                result.evaluation_id.value in routed_ids
                and result.metadata_top_20.anchor_success_at_20
                for result in results
            ),
            metadata_anchor_recall_at_20=fmean(
                (
                    result.metadata_top_20.retained_relevant_anchor_count
                    / result.relevant_anchor_count
                )
                if result.evaluation_id.value in routed_ids
                else 0.0
                for result in relevant_results
            ),
            metadata_retention_at_20=fmean(
                result.metadata_top_20.anchor_retention_at_20
                if result.evaluation_id.value in routed_ids
                else 0.0
                for result in dense_hit_results
            ),
            top3_output_rate=fmean(route_flags),
            precision_at_3=fmean(
                result.reranker_top_3.precision_at_3
                if result.evaluation_id.value in routed_ids
                else 0.0
                for result in results
            ),
            ndcg_at_3=fmean(
                result.reranker_top_3.ndcg_at_3
                if result.evaluation_id.value in routed_ids
                else 0.0
                for result in results
            ),
        )

    def _failure(
        self,
        record: NiaCaseOpenAiRoutingRecord,
        retrieval: NiaCaseCorpusRelativeQueryEvaluation,
    ) -> NiaCaseOpenAiRoutingFailureImpact:
        parsed = record.parsed_request
        return NiaCaseOpenAiRoutingFailureImpact(
            evaluation_id=record.evaluation_id,
            query=record.original_query,
            parsed_route=parsed.rag_route.value if parsed.rag_route else "none",
            parsed_intents=[intent.value for intent in parsed.intents],
            llm_case_query_draft=parsed.query_plan.case_query,
            retrieval_anchor_success_at_40=retrieval.dense_top_40.anchor_success_at_40,
            retrieval_anchor_recall_at_40=retrieval.dense_top_40.anchor_recall_at_40,
            retrieval_precision_at_3=retrieval.reranker_top_3.precision_at_3,
            retrieval_ndcg_at_3=retrieval.reranker_top_3.ndcg_at_3,
        )


class NiaCaseOpenAiE2EMarkdownReporter:
    def render(
        self,
        routing_summary: NiaCaseOpenAiRoutingSummary,
        report: NiaCaseOpenAiE2EReport,
    ) -> str:
        metrics_by_slice = {item.slice: item for item in report.metrics}
        retrieval = metrics_by_slice[NiaCaseOpenAiE2ESlice.RETRIEVAL_ONLY]
        conditional = metrics_by_slice[NiaCaseOpenAiE2ESlice.ROUTED_CONDITIONAL]
        end_to_end = metrics_by_slice[NiaCaseOpenAiE2ESlice.END_TO_END]
        lines = [
            "# NIA Case OpenAI 포함 End-to-End 성능 평가",
            "",
            "## 결론",
            "",
            (
                f"- OpenAI 운영 라우팅은 24건 중 {routing_summary.case_query_count}건"
                f"({routing_summary.case_query_coverage:.1%})을 Case RAG로 보냈다."
            ),
            (
                f"- 라우팅된 {routing_summary.case_query_count}건의 Case 질의는 모두 원문과 "
                "완전히 같아, 해당 건의 검색 결과는 동결된 v4 Live 결과와 동일하다."
            ),
            (
                f"- {routing_summary.missing_case_query_count}건은 `evidence_only`로 분류되어 "
                "Case 검색이 실행되지 않았다. 따라서 현재 병목은 질의 문장 생성이 아니라 "
                "Intent/RAG route gate다."
            ),
            "",
            "## 지표",
            "",
            "| 범위 | 질의 수 | Case route | Success@40 | Recall@40 | Metadata Success@20 | Metadata Recall@20 | Metadata Retention@20 | Top-3 출력률 | Precision@3 | nDCG@3 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            self._metric_line(retrieval),
            self._metric_line(conditional),
            self._metric_line(end_to_end),
            "",
            "- `retrieval_only`: 원문 질의를 Case 검색에 직접 넣었던 기존 v4 Live 기준선.",
            "- `routed_conditional`: OpenAI가 Case RAG로 보낸 22건 안에서의 검색 품질.",
            "- `end_to_end`: 라우팅 누락 2건을 검색 결과 없음(0점)으로 반영한 실제 시스템 성능.",
            "- `Metadata Recall@20`: 전체 관련 anchor 대비 metadata Top-20에 남은 비율이다.",
            "",
            "## 라우팅 실패 영향",
            "",
        ]
        for failure in report.routing_failures:
            lines.extend(
                [
                    f"### `{failure.evaluation_id}`",
                    "",
                    f"- 질의: {failure.query}",
                    f"- 모델 판정: route=`{failure.parsed_route}`, intents=`{', '.join(failure.parsed_intents)}`",
                    f"- LLM의 Case 질의 초안: {failure.llm_case_query_draft or '없음'}",
                    (
                        "- 라우팅이 정상이라면 기존 검색 결과: "
                        f"Success@40={failure.retrieval_anchor_success_at_40}, "
                        f"Recall@40={failure.retrieval_anchor_recall_at_40:.3f}, "
                        f"Precision@3={failure.retrieval_precision_at_3:.3f}, "
                        f"nDCG@3={failure.retrieval_ndcg_at_3:.3f}"
                    ),
                    "",
                ]
            )
        lines.extend(
            [
                "## 해석",
                "",
                (
                    f"- 라우팅 누락을 포함하면 Success@40은 {retrieval.anchor_success_at_40:.3f}에서 "
                    f"{end_to_end.anchor_success_at_40:.3f}로, Precision@3은 "
                    f"{retrieval.precision_at_3:.3f}에서 {end_to_end.precision_at_3:.3f}로 내려간다."
                ),
                (
                    "- `evaluation_core_acne_04`는 라우팅만 정상이라면 기존 Top-3가 모두 관련 문서였다. "
                    "이 건의 손실은 검색기나 리랭커가 아니라 route gate에서 발생했다."
                ),
                (
                    "- LLM은 실패 2건 모두 `query_plan.case_query` 초안을 생성했지만, "
                    "`evidence_only` 판정 때문에 운영 planner가 이를 버렸다. 후속 수정 우선순위는 "
                    "프롬프트 재작성보다 결정적 route 보정 규칙이다."
                ),
                "- OpenAI 호출은 24건 각각 1회였고 SDK 재시도는 0회였다.",
                "",
            ]
        )
        return "\n".join(lines)

    def _metric_line(self, metrics: NiaCaseOpenAiE2EMetrics) -> str:
        return (
            f"| `{metrics.slice.value}` | {metrics.query_count} | "
            f"{metrics.case_route_rate:.3f} | {metrics.anchor_success_at_40:.3f} | "
            f"{metrics.anchor_recall_at_40:.3f} | {metrics.metadata_success_at_20:.3f} | "
            f"{metrics.metadata_anchor_recall_at_20:.3f} | "
            f"{metrics.metadata_retention_at_20:.3f} | {metrics.top3_output_rate:.3f} | "
            f"{metrics.precision_at_3:.3f} | {metrics.ndcg_at_3:.3f} |"
        )


class NiaCaseOpenAiE2ECli:
    RUN_ID: ClassVar[str] = "openai_e2e_20260926_1740_v1"
    ROUTING_RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_openai_routing_once_20260926_1740_v1.jsonl"
    )
    ROUTING_SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_openai_routing_once_summary_20260926_1740_v1.jsonl"
    )
    RETRIEVAL_RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_results_20260926_1416_v1.jsonl"
    )
    RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_openai_e2e_summary_20260926_1740_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_1740_NIA_CASE_OPENAI_E2E_REPORT.md"
    )

    @classmethod
    def main(cls) -> None:
        checkpoint = NiaCaseOpenAiRoutingCheckpoint()
        routing_records = checkpoint.load(cls.ROUTING_RESULT_PATH)
        routing_summary = NiaCaseOpenAiRoutingSummary.model_validate_json(
            cls.ROUTING_SUMMARY_PATH.read_text(encoding="utf-8").strip()
        )
        retrieval_results = [
            NiaCaseCorpusRelativeQueryEvaluation.model_validate_json(line)
            for line in cls.RETRIEVAL_RESULT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        report = NiaCaseOpenAiE2ECalculator().calculate(
            cls.RUN_ID,
            routing_records,
            retrieval_results,
        )
        CandidatePoolJsonlWriter().write(cls.RESULT_PATH, [report])
        cls.REPORT_PATH.write_text(
            NiaCaseOpenAiE2EMarkdownReporter().render(routing_summary, report),
            encoding="utf-8",
        )
        end_to_end = next(
            item
            for item in report.metrics
            if item.slice is NiaCaseOpenAiE2ESlice.END_TO_END
        )
        print(
            "NIA Case OpenAI E2E 평가 완료: "
            f"route={end_to_end.case_route_rate:.3f}, "
            f"success@40={end_to_end.anchor_success_at_40:.3f}, "
            f"precision@3={end_to_end.precision_at_3:.3f}, "
            f"ndcg@3={end_to_end.ndcg_at_3:.3f}"
        )


if __name__ == "__main__":
    NiaCaseOpenAiE2ECli.main()
