"""저장된 OpenAI 응답에 현재 결정적 route 정책을 재생해 수정 효과를 평가한다."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import Field

from agent.query_planning import IntentQueryPlanner
from agent.rag.schemas import RagModel
from agent.rag_route_policy import RagRoutePolicy, RagRouteReason
from agent.schemas import QueryPlanningRequest, RagRoute
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeQueryEvaluation,
)
from tests.agent.evaluate_nia_case_openai_e2e import (
    NiaCaseOpenAiE2ECalculator,
    NiaCaseOpenAiE2EReport,
    NiaCaseOpenAiE2ESlice,
)
from tests.agent.evaluate_nia_case_openai_routing_once import (
    NiaCaseOpenAiQueryRelation,
    NiaCaseOpenAiRoutingCheckpoint,
    NiaCaseOpenAiRoutingRecord,
)
from tests.agent.nia_case_semantic_candidate_pool import CandidatePoolJsonlWriter


class NiaCaseRouteUpdateOutcome(StrEnum):
    PRESERVED = "preserved"
    CORRECTED = "corrected"
    INTENTIONAL_BYPASS = "intentional_bypass"
    REGRESSED = "regressed"


class NiaCaseRouteUpdateItem(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    original_route: RagRoute | None = None
    updated_route: RagRoute | None = None
    reason: RagRouteReason
    outcome: NiaCaseRouteUpdateOutcome
    original_case_query_draft: str | None = None
    updated_case_query: str | None = None
    case_query_relation: NiaCaseOpenAiQueryRelation


class NiaCaseRouteUpdateReport(RagModel):
    run_id: str = Field(min_length=1)
    query_count: int = Field(ge=1)
    previous_case_route_count: int = Field(ge=0)
    updated_case_route_count: int = Field(ge=0)
    corrected_count: int = Field(ge=0)
    intentional_bypass_count: int = Field(ge=0)
    regressed_count: int = Field(ge=0)
    exact_case_query_count: int = Field(ge=0)
    items: list[NiaCaseRouteUpdateItem] = Field(min_length=1)
    updated_e2e: NiaCaseOpenAiE2EReport


class NiaCaseOpenAiRouteReplayer:
    def __init__(self) -> None:
        self._policy = RagRoutePolicy()
        self._planner = IntentQueryPlanner()

    def replay(
        self,
        run_id: str,
        records: list[NiaCaseOpenAiRoutingRecord],
        retrieval_results: list[NiaCaseCorpusRelativeQueryEvaluation],
    ) -> NiaCaseRouteUpdateReport:
        items = [self._replay_record(record) for record in records]
        routed_ids = {
            item.evaluation_id
            for item in items
            if item.updated_route is RagRoute.CLAIM_THEN_EVIDENCE
            and item.updated_case_query is not None
        }
        updated_e2e = NiaCaseOpenAiE2ECalculator().calculate(
            run_id,
            records,
            retrieval_results,
            routed_ids=routed_ids,
        )
        return NiaCaseRouteUpdateReport(
            run_id=run_id,
            query_count=len(records),
            previous_case_route_count=sum(
                record.planned_query.case_query is not None for record in records
            ),
            updated_case_route_count=len(routed_ids),
            corrected_count=sum(
                item.outcome is NiaCaseRouteUpdateOutcome.CORRECTED for item in items
            ),
            intentional_bypass_count=sum(
                item.outcome is NiaCaseRouteUpdateOutcome.INTENTIONAL_BYPASS
                for item in items
            ),
            regressed_count=sum(
                item.outcome is NiaCaseRouteUpdateOutcome.REGRESSED for item in items
            ),
            exact_case_query_count=sum(
                item.case_query_relation is NiaCaseOpenAiQueryRelation.EXACT
                for item in items
            ),
            items=items,
            updated_e2e=updated_e2e,
        )

    def _replay_record(
        self,
        record: NiaCaseOpenAiRoutingRecord,
    ) -> NiaCaseRouteUpdateItem:
        parsed = record.parsed_request
        decision = self._policy.decide(parsed)
        normalized = parsed.model_copy(
            deep=True,
            update={
                "intents": decision.normalized_intents,
                "rag_route": decision.route,
                "skin_concerns": (
                    decision.normalized_skin_concerns or parsed.skin_concerns
                ),
            },
        )
        planned = self._planner.build(
            QueryPlanningRequest(
                original_message=record.original_query,
                parsed_request=normalized,
            )
        )
        previous_case_route = record.planned_query.case_query is not None
        updated_case_route = (
            decision.route is RagRoute.CLAIM_THEN_EVIDENCE
            and planned.case_query is not None
        )
        if not previous_case_route and updated_case_route:
            outcome = NiaCaseRouteUpdateOutcome.CORRECTED
        elif previous_case_route and not updated_case_route:
            outcome = (
                NiaCaseRouteUpdateOutcome.INTENTIONAL_BYPASS
                if parsed.ingredient_mentions
                else NiaCaseRouteUpdateOutcome.REGRESSED
            )
        else:
            outcome = NiaCaseRouteUpdateOutcome.PRESERVED
        return NiaCaseRouteUpdateItem(
            evaluation_id=record.evaluation_id,
            original_route=parsed.rag_route,
            updated_route=decision.route,
            reason=decision.reason,
            outcome=outcome,
            original_case_query_draft=parsed.query_plan.case_query,
            updated_case_query=planned.case_query,
            case_query_relation=self._relation(
                record.original_query,
                planned.case_query,
            ),
        )

    def _relation(
        self,
        original_query: str,
        case_query: str | None,
    ) -> NiaCaseOpenAiQueryRelation:
        if case_query is None:
            return NiaCaseOpenAiQueryRelation.MISSING
        if case_query == original_query:
            return NiaCaseOpenAiQueryRelation.EXACT
        return NiaCaseOpenAiQueryRelation.MODIFIED


class NiaCaseRouteUpdateMarkdownReporter:
    def render(self, report: NiaCaseRouteUpdateReport) -> str:
        routed_conditional = next(
            item
            for item in report.updated_e2e.metrics
            if item.slice is NiaCaseOpenAiE2ESlice.ROUTED_CONDITIONAL
        )
        all_queries = next(
            item
            for item in report.updated_e2e.metrics
            if item.slice is NiaCaseOpenAiE2ESlice.END_TO_END
        )
        corrected = [
            item
            for item in report.items
            if item.outcome is NiaCaseRouteUpdateOutcome.CORRECTED
        ]
        lines = [
            "# NIA Case 결정적 Route 보정 결과",
            "",
            "## 결과",
            "",
            f"- 저장된 OpenAI 응답: {report.query_count}건",
            f"- 수정 전 Case route: {report.previous_case_route_count}/{report.query_count}",
            f"- 수정 후 Case route: {report.updated_case_route_count}/{report.query_count}",
            f"- 복구: {report.corrected_count}건",
            f"- 명시 성분으로 Case를 의도적으로 우회: {report.intentional_bypass_count}건",
            f"- 회귀: {report.regressed_count}건",
            f"- 원문과 완전히 같은 Case query: {report.exact_case_query_count}건",
            "- 추가 OpenAI API 호출: 0회",
            "",
            "## 수정 후 End-to-End",
            "",
            "| 범위 | 질의 수 | Case route | Success@40 | Recall@40 | Metadata Success@20 | Metadata Retention@20 | Top-3 출력률 | Precision@3 | nDCG@3 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| Case 대상 | {routed_conditional.query_count} | "
                f"{routed_conditional.case_route_rate:.3f} | "
                f"{routed_conditional.anchor_success_at_40:.3f} | "
                f"{routed_conditional.anchor_recall_at_40:.3f} | "
                f"{routed_conditional.metadata_success_at_20:.3f} | "
                f"{routed_conditional.metadata_retention_at_20:.3f} | "
                f"{routed_conditional.top3_output_rate:.3f} | "
                f"{routed_conditional.precision_at_3:.3f} | "
                f"{routed_conditional.ndcg_at_3:.3f} |"
            ),
            (
                f"| 전체(명시 성분 우회 포함) | {all_queries.query_count} | "
                f"{all_queries.case_route_rate:.3f} | "
                f"{all_queries.anchor_success_at_40:.3f} | "
                f"{all_queries.anchor_recall_at_40:.3f} | "
                f"{all_queries.metadata_success_at_20:.3f} | "
                f"{all_queries.metadata_retention_at_20:.3f} | "
                f"{all_queries.top3_output_rate:.3f} | "
                f"{all_queries.precision_at_3:.3f} | {all_queries.ndcg_at_3:.3f} |"
            ),
            "",
            "전체 24건 표에서 명시 성분 우회 1건은 검색 실패가 아니라 다른 운영 경로를 선택한 것이며, 그 경로의 성능은 이 NIA Case 평가 범위에 포함하지 않는다.",
            "",
            "## 복구된 질의",
            "",
        ]
        for item in corrected:
            lines.extend(
                [
                    f"### `{item.evaluation_id}`",
                    "",
                    f"- route: `{self._route(item.original_route)}` → `{self._route(item.updated_route)}`",
                    f"- 보정 이유: `{item.reason.value}`",
                    f"- Case query: {item.updated_case_query}",
                    "",
                ]
            )
        lines.extend(
            [
                "## 적용 규칙",
                "",
                "다음 조건을 모두 만족하는 피부 고민 요청을 `claim_then_evidence`로 보정한다.",
                "",
                "1. 명시된 성분이 없다.",
                "2. 피부 고민이 추출됐다.",
                "3. LLM이 `query_plan.case_query` 초안을 생성했다.",
                "4. Evidence 질문, 루틴 요청 또는 LLM의 Case route 제안이 있다.",
                "",
                "명시 성분 Evidence 질문이나 Case 질의 초안이 없는 일반 정보 질문은 기존 `evidence_only`를 유지한다.",
                "",
            ]
        )
        return "\n".join(lines)

    def _route(self, route: RagRoute | None) -> str:
        return route.value if route else "none"


class NiaCaseOpenAiRouteUpdateCli:
    RUN_ID: ClassVar[str] = "openai_route_update_20260926_1755_v1"
    ROUTING_RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_openai_routing_once_20260926_1740_v1.jsonl"
    )
    RETRIEVAL_RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_results_20260926_1416_v1.jsonl"
    )
    RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_openai_route_update_20260926_1755_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_1755_NIA_CASE_ROUTE_UPDATE_REPORT.md"
    )

    @classmethod
    def main(cls) -> None:
        records = NiaCaseOpenAiRoutingCheckpoint().load(cls.ROUTING_RESULT_PATH)
        retrieval_results = [
            NiaCaseCorpusRelativeQueryEvaluation.model_validate_json(line)
            for line in cls.RETRIEVAL_RESULT_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        report = NiaCaseOpenAiRouteReplayer().replay(
            cls.RUN_ID,
            records,
            retrieval_results,
        )
        CandidatePoolJsonlWriter().write(cls.RESULT_PATH, [report])
        cls.REPORT_PATH.write_text(
            NiaCaseRouteUpdateMarkdownReporter().render(report),
            encoding="utf-8",
        )
        routed_conditional = next(
            item
            for item in report.updated_e2e.metrics
            if item.slice is NiaCaseOpenAiE2ESlice.ROUTED_CONDITIONAL
        )
        print(
            "NIA Case route 보정 재생 완료: "
            f"corrected={report.corrected_count}, "
            f"bypassed={report.intentional_bypass_count}, "
            f"regressed={report.regressed_count}, "
            f"eligible={routed_conditional.query_count}, "
            f"precision@3={routed_conditional.precision_at_3:.3f}"
        )


if __name__ == "__main__":
    NiaCaseOpenAiRouteUpdateCli.main()
