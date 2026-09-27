"""OpenAI 운영 Intent 해석을 24개 NIA Case 평가 질의에 한 번씩만 실행한다."""

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import Field

from agent.llm import ChatModelLlmClient
from agent.ports import LlmClient
from agent.prompts import PromptCatalog, PromptPurpose, PromptRequest
from agent.query_planning import IntentQueryPlanner
from agent.rag.schemas import ChatModelConfig, LlmProvider, ProductTaxonomy, RagModel
from agent.schemas import (
    Intent,
    IntentQueryPlan,
    LlmContext,
    ParsedRequest,
    QueryPlanningRequest,
    RagRoute,
    UnderstandingRequest,
)
from backend.services.two_layer_rag_adapters import TwoLayerProductTaxonomyProvider
from core.database import Database
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
)
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    TwoLayerAgentModelConfigFactory,
    Utf8ConsoleConfigurator,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
)


class NiaCaseOpenAiQueryRelation(StrEnum):
    EXACT = "exact"
    MODIFIED = "modified"
    MISSING = "missing"


class NiaCaseOpenAiRoutingRecord(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    original_query: str = Field(min_length=1)
    model: str = Field(min_length=1)
    configured_max_retries: int = Field(ge=0)
    effective_max_retries: int = Field(ge=0, le=0)
    invocation_ordinal: int = Field(ge=1, le=24)
    completed_at: datetime
    parsed_request: ParsedRequest
    planned_query: IntentQueryPlan
    case_query_relation: NiaCaseOpenAiQueryRelation


class NiaCaseOpenAiIntentCount(RagModel):
    intent: Intent
    query_count: int = Field(ge=0)


class NiaCaseOpenAiRouteCount(RagModel):
    route: RagRoute | None = None
    query_count: int = Field(ge=0)


class NiaCaseOpenAiRoutingSummary(RagModel):
    run_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    query_count: int = Field(ge=1)
    api_invocation_count: int = Field(ge=0)
    configured_max_retries: int = Field(ge=0)
    effective_max_retries: int = Field(ge=0, le=0)
    case_query_count: int = Field(ge=0)
    exact_case_query_count: int = Field(ge=0)
    modified_case_query_count: int = Field(ge=0)
    missing_case_query_count: int = Field(ge=0)
    case_query_coverage: float = Field(ge=0.0, le=1.0)
    exact_case_query_rate: float = Field(ge=0.0, le=1.0)
    intent_counts: list[NiaCaseOpenAiIntentCount]
    route_counts: list[NiaCaseOpenAiRouteCount]


class NiaCaseOpenAiRoutingCheckpoint:
    """성공 응답을 즉시 저장해 재실행이 이미 호출한 질의를 건너뛰게 한다."""

    def load(self, path: Path) -> list[NiaCaseOpenAiRoutingRecord]:
        if not path.exists():
            return []
        return [
            NiaCaseOpenAiRoutingRecord.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def save(self, path: Path, records: list[RagModel]) -> None:
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as destination:
                for record in records:
                    destination.write(record.model_dump_json())
                    destination.write("\n")
            temporary_path.replace(path)
        except OSError as error:
            raise RuntimeError(f"OpenAI Intent 체크포인트를 저장하지 못했습니다: {path}") from error


class NiaCaseOpenAiRoutingRunner:
    EXPECTED_QUERY_COUNT: ClassVar[int] = 24
    EFFECTIVE_MAX_RETRIES: ClassVar[int] = 0

    def __init__(
        self,
        llm: LlmClient,
        model: str,
        configured_max_retries: int,
        checkpoint: NiaCaseOpenAiRoutingCheckpoint | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._configured_max_retries = configured_max_retries
        self._checkpoint = checkpoint or NiaCaseOpenAiRoutingCheckpoint()
        self._planner = IntentQueryPlanner()
        self._prompt = PromptCatalog().get(
            PromptRequest(purpose=PromptPurpose.UNDERSTAND_REQUEST)
        )

    async def run(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        taxonomy: ProductTaxonomy,
        output_path: Path,
    ) -> list[NiaCaseOpenAiRoutingRecord]:
        self._validate_queries(queries)
        existing = self._checkpoint.load(output_path)
        records_by_id = {record.evaluation_id: record for record in existing}
        self._validate_checkpoint(queries, existing)

        for query in queries:
            if query.evaluation_id in records_by_id:
                continue
            parsed = await self._llm.understand(
                UnderstandingRequest(
                    message=query.query,
                    system_prompt=self._prompt.system_message,
                    context=LlmContext(),
                    product_taxonomy=taxonomy.model_copy(deep=True),
                )
            )
            planned = self._planner.build(
                QueryPlanningRequest(
                    original_message=query.query,
                    parsed_request=parsed,
                )
            )
            relation = self._relation(query.query, planned.case_query)
            record = NiaCaseOpenAiRoutingRecord(
                evaluation_id=query.evaluation_id,
                original_query=query.query,
                model=self._model,
                configured_max_retries=self._configured_max_retries,
                effective_max_retries=self.EFFECTIVE_MAX_RETRIES,
                invocation_ordinal=len(records_by_id) + 1,
                completed_at=datetime.now(UTC),
                parsed_request=parsed,
                planned_query=planned,
                case_query_relation=relation,
            )
            records_by_id[query.evaluation_id] = record
            ordered = [
                records_by_id[item.evaluation_id]
                for item in queries
                if item.evaluation_id in records_by_id
            ]
            # API 성공 직후 저장해야 중단 후 재개해도 같은 질의를 다시 과금하지 않는다.
            self._checkpoint.save(output_path, ordered)
            print(
                f"{len(ordered)}/{len(queries)} {query.evaluation_id}: "
                f"route={parsed.rag_route.value if parsed.rag_route else 'none'}, "
                f"case_query={relation.value}"
            )
        return [records_by_id[query.evaluation_id] for query in queries]

    def _validate_queries(self, queries: list[NiaCaseSemanticEvaluationQuery]) -> None:
        if len(queries) != self.EXPECTED_QUERY_COUNT:
            raise RuntimeError(
                "OpenAI 1회 평가 질의 수가 동결된 24건과 다릅니다: "
                f"queries={len(queries)}"
            )
        evaluation_ids = [query.evaluation_id for query in queries]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise RuntimeError("OpenAI 1회 평가 질의 ID가 중복됐습니다.")

    def _validate_checkpoint(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        records: list[NiaCaseOpenAiRoutingRecord],
    ) -> None:
        query_by_id = {query.evaluation_id: query for query in queries}
        record_ids = [record.evaluation_id for record in records]
        if len(record_ids) != len(set(record_ids)):
            raise RuntimeError("OpenAI Intent 체크포인트에 중복 질의가 있습니다.")
        unexpected = set(record_ids) - set(query_by_id)
        if unexpected:
            raise RuntimeError(f"체크포인트에 알 수 없는 질의가 있습니다: {sorted(unexpected)}")
        for record in records:
            query = query_by_id[record.evaluation_id]
            if record.original_query != query.query or record.model != self._model:
                raise RuntimeError(
                    "체크포인트의 질의 또는 모델이 현재 평가 조건과 다릅니다: "
                    f"evaluation_id={record.evaluation_id}"
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


class NiaCaseOpenAiRoutingSummarizer:
    def summarize(
        self,
        run_id: str,
        records: list[NiaCaseOpenAiRoutingRecord],
    ) -> NiaCaseOpenAiRoutingSummary:
        if not records:
            raise RuntimeError("요약할 OpenAI Intent 결과가 없습니다.")
        model = records[0].model
        configured_max_retries = records[0].configured_max_retries
        case_query_count = sum(
            record.planned_query.case_query is not None for record in records
        )
        exact_count = sum(
            record.case_query_relation is NiaCaseOpenAiQueryRelation.EXACT
            for record in records
        )
        modified_count = sum(
            record.case_query_relation is NiaCaseOpenAiQueryRelation.MODIFIED
            for record in records
        )
        missing_count = sum(
            record.case_query_relation is NiaCaseOpenAiQueryRelation.MISSING
            for record in records
        )
        intent_counts = [
            NiaCaseOpenAiIntentCount(
                intent=intent,
                query_count=sum(
                    intent in record.parsed_request.intents for record in records
                ),
            )
            for intent in Intent
        ]
        route_values: list[RagRoute | None] = [*RagRoute, None]
        route_counts = [
            NiaCaseOpenAiRouteCount(
                route=route,
                query_count=sum(
                    record.parsed_request.rag_route is route for record in records
                ),
            )
            for route in route_values
        ]
        return NiaCaseOpenAiRoutingSummary(
            run_id=run_id,
            model=model,
            query_count=len(records),
            api_invocation_count=len(records),
            configured_max_retries=configured_max_retries,
            effective_max_retries=NiaCaseOpenAiRoutingRunner.EFFECTIVE_MAX_RETRIES,
            case_query_count=case_query_count,
            exact_case_query_count=exact_count,
            modified_case_query_count=modified_count,
            missing_case_query_count=missing_count,
            case_query_coverage=case_query_count / len(records),
            exact_case_query_rate=exact_count / len(records),
            intent_counts=intent_counts,
            route_counts=route_counts,
        )


class NiaCaseOpenAiRoutingMarkdownReporter:
    def render(
        self,
        summary: NiaCaseOpenAiRoutingSummary,
        records: list[NiaCaseOpenAiRoutingRecord],
    ) -> str:
        lines = [
            "# NIA Case OpenAI 운영 Intent 1회 평가",
            "",
            "## 실행 조건",
            "",
            f"- 실행 ID: `{summary.run_id}`",
            f"- 모델: `{summary.model}`",
            f"- 질의: {summary.query_count}건",
            f"- 애플리케이션 API 호출: {summary.api_invocation_count}회",
            f"- 운영 설정 재시도: {summary.configured_max_retries}회",
            f"- 이번 평가 재시도: {summary.effective_max_retries}회",
            "- 입력: 동결된 NIA Case 코퍼스 상대 평가 질의 24건",
            "- 범위: OpenAI Intent/RAG route 해석과 운영 IntentQueryPlanner의 case_query 생성",
            "",
            "## 결과",
            "",
            (
                f"- Case query 생성: {summary.case_query_count}/{summary.query_count} "
                f"({summary.case_query_coverage:.1%})"
            ),
            (
                f"- 원문과 완전 일치: "
                f"{summary.exact_case_query_count}/{summary.query_count} "
                f"({summary.exact_case_query_rate:.1%})"
            ),
            f"- 수정된 Case query: {summary.modified_case_query_count}건",
            f"- Case query 누락: {summary.missing_case_query_count}건",
            "",
            "### RAG route 분포",
            "",
            "| route | 질의 수 |",
            "| --- | ---: |",
            *[
                f"| `{item.route.value if item.route else 'none'}` | {item.query_count} |"
                for item in summary.route_counts
            ],
            "",
            "### Intent 분포",
            "",
            "| intent | 질의 수 |",
            "| --- | ---: |",
            *[
                f"| `{item.intent.value}` | {item.query_count} |"
                for item in summary.intent_counts
                if item.query_count > 0
            ],
            "",
            "## 질의별 판정",
            "",
            "| evaluation_id | route | intents | case query 관계 | 생성 질의 |",
            "| --- | --- | --- | --- | --- |",
            *[
                self._record_line(record)
                for record in records
            ],
            "",
            "## 해석 기준",
            "",
            "- `exact`이면 OpenAI가 route와 Intent를 정하더라도 실제 Case 임베딩 질의는 원문과 같습니다.",
            "- `modified`이면 해당 질의는 생성된 Case 질의로 BGE-M3 검색을 다시 평가해야 합니다.",
            "- `missing`이면 OpenAI 라우팅 단계에서 Case RAG에 진입하지 못한 실패로 봅니다.",
            "- 이 실행은 OpenAI가 검색 정답을 생성하는 평가가 아니라, 운영 라우팅이 동결 질의를 NIA Case 검색으로 넘기는지 확인하는 평가입니다.",
            "",
        ]
        return "\n".join(lines)

    def _record_line(self, record: NiaCaseOpenAiRoutingRecord) -> str:
        route = record.parsed_request.rag_route
        intents = ", ".join(intent.value for intent in record.parsed_request.intents)
        case_query = record.planned_query.case_query or "-"
        escaped_query = case_query.replace("|", "\\|").replace("\n", " ")
        return (
            f"| `{record.evaluation_id}` | `{route.value if route else 'none'}` | "
            f"`{intents}` | `{record.case_query_relation.value}` | {escaped_query} |"
        )


class NiaCaseOpenAiRoutingOnceCli:
    RUN_ID: ClassVar[str] = "openai_routing_once_20260926_1740_v1"
    RESULT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_openai_routing_once_20260926_1740_v1.jsonl"
    )
    SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_openai_routing_once_summary_20260926_1740_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_1740_NIA_CASE_OPENAI_ROUTING_ONCE_REPORT.md"
    )

    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        queries = NiaCaseSemanticEvaluationQueryLoader().load(
            NiaCaseCorpusRelativeEvaluationCli.QUERY_PATH
        ).items
        config = TwoLayerAgentModelConfigFactory().create_chat()
        if config.provider is not LlmProvider.OPENAI or config.openai is None:
            raise RuntimeError("이번 1회 평가는 config.yaml의 OpenAI 채팅 설정이 필요합니다.")
        configured_max_retries = config.openai.max_retries
        one_shot_config: ChatModelConfig = config.model_copy(
            update={
                "openai": config.openai.model_copy(
                    update={"max_retries": NiaCaseOpenAiRoutingRunner.EFFECTIVE_MAX_RETRIES}
                )
            }
        )

        database: Database = ConfiguredDatabaseFactory().create()
        try:
            taxonomy = await TwoLayerProductTaxonomyProvider(
                database.session_factory
            ).load()
        finally:
            await database.dispose()

        runner = NiaCaseOpenAiRoutingRunner(
            llm=ChatModelLlmClient(one_shot_config),
            model=one_shot_config.active_model(),
            configured_max_retries=configured_max_retries,
        )
        records = await runner.run(queries, taxonomy, cls.RESULT_PATH)
        summary = NiaCaseOpenAiRoutingSummarizer().summarize(cls.RUN_ID, records)
        NiaCaseOpenAiRoutingCheckpoint().save(cls.SUMMARY_PATH, [summary])
        cls.REPORT_PATH.write_text(
            NiaCaseOpenAiRoutingMarkdownReporter().render(summary, records),
            encoding="utf-8",
        )
        print(
            "OpenAI 운영 Intent 1회 평가 완료: "
            f"queries={summary.query_count}, "
            f"case_query={summary.case_query_count}, "
            f"exact={summary.exact_case_query_count}, "
            f"modified={summary.modified_case_query_count}, "
            f"missing={summary.missing_case_query_count}"
        )


if __name__ == "__main__":
    asyncio.run(NiaCaseOpenAiRoutingOnceCli.main())
