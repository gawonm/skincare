"""후보 보존형 리랭커의 추가 판정을 병합하고 Top-3 관련성 평가를 확정한다."""

from enum import StrEnum
from pathlib import Path
from statistics import fmean
from typing import ClassVar, TypeVar

from pydantic import AliasChoices, Field

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeGoldenCase,
    NiaCaseCorpusRelativeGoldenEvaluator,
    NiaCaseCorpusRelativeQueryEvaluation,
)
from tests.agent.evaluate_nia_case_corpus_relative_live_v3 import (
    NiaCaseCorpusRelativeLiveProbeItem,
)
from tests.agent.finalize_nia_case_corpus_relative_live_v3 import (
    NiaCaseCorpusRelativeLiveGoldenExpander,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    CorpusRelevanceGrade,
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
)

RerankerFinalizerModel = TypeVar("RerankerFinalizerModel", bound=RagModel)


class NiaCaseRerankerEvaluationScope(StrEnum):
    ALL = "all_24"
    CASE_ROUTE = "case_route_23"


class NiaCaseRerankerTop3Metrics(RagModel):
    scope: NiaCaseRerankerEvaluationScope
    query_count: int = Field(ge=1)
    # 기존 요약 파일과 호환하면서 표준 IR 용어로 산출물을 내보낸다.
    hit_rate_at_3: float = Field(
        validation_alias=AliasChoices("hit_rate_at_3", "success_at_3"),
        ge=0.0,
        le=1.0,
    )
    precision_at_3: float = Field(ge=0.0, le=1.0)
    grade_3_hit_rate_at_3: float = Field(
        validation_alias=AliasChoices(
            "grade_3_hit_rate_at_3",
            "highly_relevant_success_at_3",
        ),
        ge=0.0,
        le=1.0,
    )
    ndcg_at_3_reference: float = Field(ge=0.0, le=1.0)
    direction_conflict_total: int = Field(ge=0)
    exact_duplicate_total: int = Field(ge=0)


class NiaCaseRerankerQueryComparison(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    before_case_ids: list[str] = Field(min_length=3, max_length=3)
    after_case_ids: list[str] = Field(min_length=3, max_length=3)
    before_grades: list[CorpusRelevanceGrade] = Field(min_length=3, max_length=3)
    after_grades: list[CorpusRelevanceGrade] = Field(min_length=3, max_length=3)
    membership_changed: bool
    before_hit_rate_at_3: bool = Field(
        validation_alias=AliasChoices("before_hit_rate_at_3", "before_success_at_3")
    )
    after_hit_rate_at_3: bool = Field(
        validation_alias=AliasChoices("after_hit_rate_at_3", "after_success_at_3")
    )
    before_precision_at_3: float = Field(ge=0.0, le=1.0)
    after_precision_at_3: float = Field(ge=0.0, le=1.0)


class NiaCaseRerankerRelevanceSummary(RagModel):
    run_id: str = Field(min_length=1)
    added_qrel_count: int = Field(ge=1)
    candidate_count_min: int = Field(ge=1)
    candidate_count_max: int = Field(ge=1)
    before_all: NiaCaseRerankerTop3Metrics
    after_all: NiaCaseRerankerTop3Metrics
    before_case_route: NiaCaseRerankerTop3Metrics
    after_case_route: NiaCaseRerankerTop3Metrics
    membership_changed_count: int = Field(ge=0)
    hit_rate_gain_count: int = Field(
        validation_alias=AliasChoices("hit_rate_gain_count", "success_gain_count"),
        ge=0,
    )
    hit_rate_loss_count: int = Field(
        validation_alias=AliasChoices("hit_rate_loss_count", "success_loss_count"),
        ge=0,
    )
    comparisons: list[NiaCaseRerankerQueryComparison] = Field(min_length=1)


class NiaCaseRerankerRelevanceReporter:
    def render(self, summary: NiaCaseRerankerRelevanceSummary) -> str:
        lines = [
            "# NIA Case 후보 보존형 리랭커 관련성 평가",
            "",
            "## 평가 목적",
            "",
            "- Top-3 내부의 세부 순서보다 관련 사례 포함 여부와 관련 사례 비율을 우선한다.",
            "- 기존 Dense Top-40을 재사용했으며 임베딩 벡터와 DB 검색 결과는 변경하지 않았다.",
            "- 메타데이터는 후보 제거가 아니라 우선순위 신호로만 사용하고 40건을 리랭커에 전달했다.",
            "- `[추론]`을 제외한 사례 질문·답변과 메타데이터를 BGE 리랭커 입력으로 사용했다.",
            (
                "- 재사용한 평가 후보 풀도 질문·답변만 보존하므로 `[추론]` 제거의 성능 효과는 "
                "이번 비교에서 분리 측정되지 않았다."
            ),
            "",
            "## 실행 결과",
            "",
            f"- 실행 ID: `{summary.run_id}`",
            f"- 추가 판정: {summary.added_qrel_count}건",
            (
                "- 질의별 리랭커 후보: "
                f"{summary.candidate_count_min}~{summary.candidate_count_max}건"
            ),
            f"- Top-3 구성이 달라진 질의: {summary.membership_changed_count}건",
            (
                "- Hit Rate@3 개선/하락: "
                f"{summary.hit_rate_gain_count}/{summary.hit_rate_loss_count}건"
            ),
            "",
            "## 핵심 지표",
            "",
            (
                "| 범위 | 시점 | Hit Rate@3 | Precision@3 | Grade-3 Hit Rate@3 | "
                "nDCG@3(참고) | 피부 상태-관리 부적합 | 정확 중복 |"
            ),
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            *self._metric_rows(summary),
            "",
            "## Top-3 구성이 달라진 질의",
            "",
            "| 질의 | 이전 등급 | 이후 등급 | Precision@3 변화 | Hit Rate@3 |",
            "| --- | --- | --- | ---: | --- |",
            *self._comparison_rows(summary.comparisons),
            "",
            "## 해석",
            "",
            "- `Hit Rate@3`는 등급 2 이상의 관련 사례가 Top-3에 하나 이상 있는 질의 비율이다.",
            "- `Grade-3 Hit Rate@3`는 등급 3 사례가 Top-3에 하나 이상 있는 질의 비율이다.",
            "- `Precision@3`는 Top-3 중 등급 2 이상인 사례의 비율이다.",
            "- `nDCG@3`는 내부 순서를 반영하므로 이번 의사결정에서는 참고값으로만 둔다.",
            (
                "- 이번 전후 수치는 주로 리랭커 후보를 20건에서 40건으로 늘리고 "
                "정확 중복을 제거한 효과를 나타낸다."
            ),
            "- 평가는 전체 임상 정답이 아니라 현재 NIA Case 코퍼스 안에서 판정된 qrel 기준이다.",
            "",
        ]
        return "\n".join(lines)

    def _metric_rows(self, summary: NiaCaseRerankerRelevanceSummary) -> list[str]:
        rows: list[str] = []
        for label, timing, metrics in (
            ("전체 24", "이전", summary.before_all),
            ("전체 24", "이후", summary.after_all),
            ("Case route 23", "이전", summary.before_case_route),
            ("Case route 23", "이후", summary.after_case_route),
        ):
            rows.append(
                f"| {label} | {timing} | {metrics.hit_rate_at_3:.3f} | "
                f"{metrics.precision_at_3:.3f} | "
                f"{metrics.grade_3_hit_rate_at_3:.3f} | "
                f"{metrics.ndcg_at_3_reference:.3f} | "
                f"{metrics.direction_conflict_total} | {metrics.exact_duplicate_total} |"
            )
        return rows

    def _comparison_rows(
        self,
        comparisons: list[NiaCaseRerankerQueryComparison],
    ) -> list[str]:
        changed = [item for item in comparisons if item.membership_changed]
        if not changed:
            return ["| 변경 없음 | - | - | 0.000 | - |"]
        return [
            f"| `{item.evaluation_id}` | "
            f"{','.join(str(int(grade)) for grade in item.before_grades)} | "
            f"{','.join(str(int(grade)) for grade in item.after_grades)} | "
            f"{item.after_precision_at_3 - item.before_precision_at_3:+.3f} | "
            f"{self._hit_rate_change(item)} |"
            for item in changed
        ]

    def _hit_rate_change(self, item: NiaCaseRerankerQueryComparison) -> str:
        if item.before_hit_rate_at_3 == item.after_hit_rate_at_3:
            return "유지"
        return "개선" if item.after_hit_rate_at_3 else "하락"


class NiaCaseRerankerRelevanceV5FinalizerCli:
    RUN_ID: ClassVar[str] = "reranker_relevance_20260926_2150_v1"
    EXCLUDED_CASE_ROUTE_EVALUATION_ID: ClassVar[str] = (
        "evaluation_rare_wrinkles_02"
    )
    GOLDEN_V4_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v4.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )
    BEFORE_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_probe_20260926_1416_v1.jsonl"
    )
    AFTER_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_reranker_relevance_probe_20260926_2150_v1.jsonl"
    )
    UNJUDGED_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_reranker_relevance_unjudged_20260926_2150_v1.jsonl"
    )
    SUPPLEMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_reranker_relevance_supplement_judgments_20260926_2150_v1.jsonl"
    )
    GOLDEN_V5_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v5.jsonl"
    )
    EVALUATION_V5_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_evaluation_results_v5.jsonl"
    )
    SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_reranker_relevance_final_summary_20260926_2150_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_2150_NIA_CASE_RERANKER_RELEVANCE_V5_REPORT.md"
    )

    @classmethod
    def main(cls) -> None:
        queries = NiaCaseSemanticEvaluationQueryLoader().load(
            NiaCaseCorpusRelativeEvaluationCli.QUERY_PATH
        ).items
        internal_items = CandidatePoolArtifactLoader().load_internal(
            cls.LIVE_POOL_PATH
        )
        before_probes = cls._load_models(
            cls.BEFORE_PROBE_PATH,
            NiaCaseCorpusRelativeLiveProbeItem,
        )
        after_probes = cls._load_models(
            cls.AFTER_PROBE_PATH,
            NiaCaseCorpusRelativeLiveProbeItem,
        )
        expansion = NiaCaseCorpusRelativeLiveGoldenExpander().expand(
            golden_cases=cls._load_models(
                cls.GOLDEN_V4_PATH,
                NiaCaseCorpusRelativeGoldenCase,
            ),
            internal_items=internal_items,
            unjudged_items=CandidatePoolArtifactLoader().load_blind(
                cls.UNJUDGED_PATH
            ),
            supplement_batches=cls._load_models(
                cls.SUPPLEMENT_PATH,
                NiaCaseCorpusRelevanceJudgmentBatch,
            ),
        )
        evaluator = NiaCaseCorpusRelativeGoldenEvaluator()
        before_report = evaluator.evaluate(
            queries,
            expansion.golden_cases,
            internal_items,
            before_probes,
        )
        after_report = evaluator.evaluate(
            queries,
            expansion.golden_cases,
            internal_items,
            after_probes,
        )
        comparisons = cls._compare(before_report.queries, after_report.queries)
        before_case_route = [
            item
            for item in before_report.queries
            if item.evaluation_id.value != cls.EXCLUDED_CASE_ROUTE_EVALUATION_ID
        ]
        after_case_route = [
            item
            for item in after_report.queries
            if item.evaluation_id.value != cls.EXCLUDED_CASE_ROUTE_EVALUATION_ID
        ]
        candidate_counts = [item.metadata_candidate_count for item in after_probes]
        summary = NiaCaseRerankerRelevanceSummary(
            run_id=cls.RUN_ID,
            added_qrel_count=expansion.added_qrel_count,
            candidate_count_min=min(candidate_counts),
            candidate_count_max=max(candidate_counts),
            before_all=cls._metrics(
                NiaCaseRerankerEvaluationScope.ALL,
                before_report.queries,
            ),
            after_all=cls._metrics(
                NiaCaseRerankerEvaluationScope.ALL,
                after_report.queries,
            ),
            before_case_route=cls._metrics(
                NiaCaseRerankerEvaluationScope.CASE_ROUTE,
                before_case_route,
            ),
            after_case_route=cls._metrics(
                NiaCaseRerankerEvaluationScope.CASE_ROUTE,
                after_case_route,
            ),
            membership_changed_count=sum(
                item.membership_changed for item in comparisons
            ),
            hit_rate_gain_count=sum(
                not item.before_hit_rate_at_3 and item.after_hit_rate_at_3
                for item in comparisons
            ),
            hit_rate_loss_count=sum(
                item.before_hit_rate_at_3 and not item.after_hit_rate_at_3
                for item in comparisons
            ),
            comparisons=comparisons,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.GOLDEN_V5_PATH, list(expansion.golden_cases))
        writer.write(cls.EVALUATION_V5_PATH, list(after_report.queries))
        writer.write(cls.SUMMARY_PATH, [summary])
        cls.REPORT_PATH.write_text(
            NiaCaseRerankerRelevanceReporter().render(summary),
            encoding="utf-8",
        )
        print(
            "후보 보존형 리랭커 평가 확정: "
            f"added_qrels={summary.added_qrel_count}, "
            f"hit_rate@3={summary.after_case_route.hit_rate_at_3:.3f}, "
            f"precision@3={summary.after_case_route.precision_at_3:.3f}, "
            f"duplicates={summary.after_case_route.exact_duplicate_total}"
        )

    @classmethod
    def _metrics(
        cls,
        scope: NiaCaseRerankerEvaluationScope,
        items: list[NiaCaseCorpusRelativeQueryEvaluation],
    ) -> NiaCaseRerankerTop3Metrics:
        return NiaCaseRerankerTop3Metrics(
            scope=scope,
            query_count=len(items),
            hit_rate_at_3=fmean(
                any(
                    grade >= CorpusRelevanceGrade.RELEVANT
                    for grade in item.reranker_top_3.grades
                )
                for item in items
            ),
            precision_at_3=fmean(
                item.reranker_top_3.precision_at_3 for item in items
            ),
            grade_3_hit_rate_at_3=fmean(
                item.reranker_top_3.grade_3_hit_rate_at_3
                for item in items
            ),
            ndcg_at_3_reference=fmean(
                item.reranker_top_3.ndcg_at_3 for item in items
            ),
            direction_conflict_total=sum(
                item.reranker_top_3.direction_conflict_at_3 for item in items
            ),
            exact_duplicate_total=sum(
                item.reranker_top_3.exact_duplicate_at_3 for item in items
            ),
        )

    @classmethod
    def _compare(
        cls,
        before: list[NiaCaseCorpusRelativeQueryEvaluation],
        after: list[NiaCaseCorpusRelativeQueryEvaluation],
    ) -> list[NiaCaseRerankerQueryComparison]:
        before_by_id = {item.evaluation_id: item for item in before}
        return [
            cls._comparison(before_by_id[item.evaluation_id], item)
            for item in after
        ]

    @classmethod
    def _comparison(
        cls,
        before: NiaCaseCorpusRelativeQueryEvaluation,
        after: NiaCaseCorpusRelativeQueryEvaluation,
    ) -> NiaCaseRerankerQueryComparison:
        before_hit = any(
            grade >= CorpusRelevanceGrade.RELEVANT
            for grade in before.reranker_top_3.grades
        )
        after_hit = any(
            grade >= CorpusRelevanceGrade.RELEVANT
            for grade in after.reranker_top_3.grades
        )
        return NiaCaseRerankerQueryComparison(
            evaluation_id=after.evaluation_id.value,
            before_case_ids=before.reranker_top_3.case_ids,
            after_case_ids=after.reranker_top_3.case_ids,
            before_grades=before.reranker_top_3.grades,
            after_grades=after.reranker_top_3.grades,
            membership_changed=(
                set(before.reranker_top_3.case_ids)
                != set(after.reranker_top_3.case_ids)
            ),
            before_hit_rate_at_3=before_hit,
            after_hit_rate_at_3=after_hit,
            before_precision_at_3=before.reranker_top_3.precision_at_3,
            after_precision_at_3=after.reranker_top_3.precision_at_3,
        )

    @classmethod
    def _load_models(
        cls,
        path: Path,
        model_type: type[RerankerFinalizerModel],
    ) -> list[RerankerFinalizerModel]:
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    NiaCaseRerankerRelevanceV5FinalizerCli.main()
