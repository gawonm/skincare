"""피부 상태-관리 부적합 안전 필터가 문제 질의의 Top-3를 바꾸는지 확인한다."""

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import Field

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeGoldenCase,
    NiaCaseCorpusRelativeGradedQrel,
)
from tests.agent.evaluate_nia_case_corpus_relative_live_v3 import (
    NiaCaseCorpusRelativeLiveProbe,
    NiaCaseCorpusRelativeLiveProbeItem,
)
from tests.agent.interactive_two_layer_rag_cli import Utf8ConsoleConfigurator
from tests.agent.nia_case_corpus_relevance_schemas import (
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

CareCompatibilityProbeModel = TypeVar(
    "CareCompatibilityProbeModel",
    bound=RagModel,
)


class CareCompatibilityEvaluationId(StrEnum):
    IRRITATED_PORES = "evaluation_core_pores_08"
    SENSITIVE_STABILIZATION = "evaluation_rare_sensitive_01"


class CareCompatibilityQueryComparison(RagModel):
    evaluation_id: CareCompatibilityEvaluationId
    before_case_ids: list[str] = Field(max_length=3)
    after_case_ids: list[str] = Field(max_length=3)
    before_grades: list[int | None] = Field(max_length=3)
    after_grades: list[int | None] = Field(max_length=3)
    before_known_mismatch_count: int = Field(ge=0, le=3)
    after_known_mismatch_count: int = Field(ge=0, le=3)
    after_unjudged_count: int = Field(ge=0, le=3)


class CareCompatibilityProbeSummary(RagModel):
    run_id: str = Field(min_length=1)
    query_count: int = Field(ge=1)
    before_known_mismatch_total: int = Field(ge=0)
    after_known_mismatch_total: int = Field(ge=0)
    after_unjudged_total: int = Field(ge=0)
    comparisons: list[CareCompatibilityQueryComparison] = Field(min_length=1)


class CareCompatibilityProbeReporter:
    def render(self, summary: CareCompatibilityProbeSummary) -> str:
        lines = [
            "# NIA Case 피부 상태-관리 부적합 안전 브레이크 집중 점검",
            "",
            "## 목적",
            "",
            "- 화끈거림·따가움·붉어짐과 안정화·장벽 회복을 함께 요청한 질의만 대상으로 한다.",
            "- 해당 상태에서 BHA·레티놀·반복 각질 제거·강한 세안을 권하는 답변은 제외한다.",
            "- 적합한 Case가 남지 않으면 위험 답변으로 Top-3를 채우지 않고 Case 결과를 보류한다.",
            "- Dense Top-40과 BGE 점수 계산 방식은 유지하고 하이브리드 검색은 사용하지 않는다.",
            "",
            "## 집중 점검 결과",
            "",
            f"- 질의: {summary.query_count}건",
            (
                "- 기존 피부 상태-관리 부적합 노출: "
                f"{summary.before_known_mismatch_total}건"
            ),
            (
                "- 변경 후 기존 판정 기준으로 확인된 부적합 노출: "
                f"{summary.after_known_mismatch_total}건"
            ),
            f"- 변경 후 신규 판정 필요 후보: {summary.after_unjudged_total}건",
            "",
            "| 질의 | 이전 Top-3 등급 | 이후 Top-3 등급 | 이전 부적합 | 이후 확인 부적합 | 신규 판정 |",
            "| --- | --- | --- | ---: | ---: | ---: |",
            *self._rows(summary.comparisons),
            "",
            "## 해석 제한",
            "",
            self._interpretation(summary),
            "",
        ]
        return "\n".join(lines)

    def _rows(
        self,
        comparisons: list[CareCompatibilityQueryComparison],
    ) -> list[str]:
        return [
            f"| `{item.evaluation_id.value}` | "
            f"{self._grades(item.before_grades)} | {self._grades(item.after_grades)} | "
            f"{item.before_known_mismatch_count} | "
            f"{item.after_known_mismatch_count} | {item.after_unjudged_count} |"
            for item in comparisons
        ]

    def _grades(self, grades: list[int | None]) -> str:
        if not grades:
            return "결과 없음"
        return ",".join("?" if grade is None else str(grade) for grade in grades)

    def _interpretation(self, summary: CareCompatibilityProbeSummary) -> str:
        if summary.after_unjudged_total:
            return (
                "신규 Top-3 후보는 기존 qrel에 없으면 관련성 등급과 관리 적합성을 "
                "블라인드 판정해야 한다. 따라서 신규 판정 전에는 개선을 확정하지 않는다."
            )
        return (
            "신규 노출 후보의 보완 판정까지 완료했다. 이 결과는 문제 유형 2건에 대한 "
            "집중 점검이므로 전체 24개 질의의 성능 변화는 별도 회귀 평가로 확인한다."
        )


class NiaCaseCareCompatibilityProbeCli:
    RUN_ID: ClassVar[str] = "care_compatibility_20260927_v1"
    QUERY_PATH: ClassVar[Path] = NiaCaseCorpusRelativeEvaluationCli.QUERY_PATH
    GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_golden_v5.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )
    BASELINE_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_reranker_relevance_probe_20260926_2150_v1.jsonl"
    )
    PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_care_compatibility_probe_20260927_v1.jsonl"
    )
    UNJUDGED_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_care_compatibility_unjudged_20260927_v1.jsonl"
    )
    SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_care_compatibility_summary_20260927_v1.jsonl"
    )
    SUPPLEMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_care_compatibility_supplement_judgments_20260927_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-27_NIA_CASE_CARE_COMPATIBILITY_PROBE.md"
    )

    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        target_ids = {item.value for item in CareCompatibilityEvaluationId}
        queries = [
            item
            for item in NiaCaseSemanticEvaluationQueryLoader().load(
                cls.QUERY_PATH
            ).items
            if item.evaluation_id in target_ids
        ]
        internal_items = [
            item
            for item in CandidatePoolArtifactLoader().load_internal(
                cls.LIVE_POOL_PATH
            )
            if item.evaluation_id in target_ids
        ]
        golden_cases = [
            item
            for item in cls._load_models(
                cls.GOLDEN_PATH,
                NiaCaseCorpusRelativeGoldenCase,
            )
            if item.evaluation_id.value in target_ids
        ]
        baseline_items = [
            item
            for item in cls._load_models(
                cls.BASELINE_PROBE_PATH,
                NiaCaseCorpusRelativeLiveProbeItem,
            )
            if item.evaluation_id in target_ids
        ]
        result = await NiaCaseCorpusRelativeLiveProbe().run(
            queries,
            internal_items,
            golden_cases,
        )
        summary = cls._summarize(
            baseline_items,
            result.items,
            golden_cases,
            cls._load_models(
                cls.SUPPLEMENT_PATH,
                NiaCaseCorpusRelevanceJudgmentBatch,
            ),
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.PROBE_PATH, result.items)
        writer.write(cls.UNJUDGED_PATH, result.unjudged_items)
        writer.write(cls.SUMMARY_PATH, [summary])
        cls.REPORT_PATH.write_text(
            CareCompatibilityProbeReporter().render(summary),
            encoding="utf-8",
        )
        print(
            "피부 상태-관리 부적합 안전 브레이크 집중 점검 완료: "
            f"before={summary.before_known_mismatch_total}, "
            f"after_known={summary.after_known_mismatch_total}, "
            f"unjudged={summary.after_unjudged_total}"
        )

    @classmethod
    def _summarize(
        cls,
        before_items: list[NiaCaseCorpusRelativeLiveProbeItem],
        after_items: list[NiaCaseCorpusRelativeLiveProbeItem],
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase],
        supplement_batches: list[NiaCaseCorpusRelevanceJudgmentBatch],
    ) -> CareCompatibilityProbeSummary:
        before_by_id = {item.evaluation_id: item for item in before_items}
        golden_by_id = {item.evaluation_id.value: item for item in golden_cases}
        supplement_by_id = {
            item.evaluation_id: item.judgments for item in supplement_batches
        }
        comparisons = [
            cls._compare(
                before_by_id[item.evaluation_id],
                item,
                golden_by_id[item.evaluation_id],
                supplement_by_id.get(item.evaluation_id, []),
            )
            for item in after_items
        ]
        return CareCompatibilityProbeSummary(
            run_id=cls.RUN_ID,
            query_count=len(comparisons),
            before_known_mismatch_total=sum(
                item.before_known_mismatch_count for item in comparisons
            ),
            after_known_mismatch_total=sum(
                item.after_known_mismatch_count for item in comparisons
            ),
            after_unjudged_total=sum(
                item.after_unjudged_count for item in comparisons
            ),
            comparisons=comparisons,
        )

    @classmethod
    def _compare(
        cls,
        before: NiaCaseCorpusRelativeLiveProbeItem,
        after: NiaCaseCorpusRelativeLiveProbeItem,
        golden: NiaCaseCorpusRelativeGoldenCase,
        supplements: list[NiaCaseCorpusRelevanceJudgment],
    ) -> CareCompatibilityQueryComparison:
        qrels_by_key = {item.review_key: item for item in golden.graded_qrels}
        judgments_by_key: dict[str, NiaCaseCorpusRelevanceJudgment] = {
            item.review_key: item for item in supplements
        }
        before_qrels = [qrels_by_key.get(hit.review_key) for hit in before.hits]
        after_judgments = [
            judgments_by_key.get(hit.review_key) for hit in after.hits
        ]
        after_qrels = [qrels_by_key.get(hit.review_key) for hit in after.hits]
        return CareCompatibilityQueryComparison(
            evaluation_id=CareCompatibilityEvaluationId(after.evaluation_id),
            before_case_ids=[hit.case_id for hit in before.hits],
            after_case_ids=[hit.case_id for hit in after.hits],
            before_grades=[
                None if qrel is None else int(qrel.relevance_grade)
                for qrel in before_qrels
            ],
            after_grades=[
                cls._resolved_grade(qrel, judgment)
                for qrel, judgment in zip(
                    after_qrels,
                    after_judgments,
                    strict=True,
                )
            ],
            before_known_mismatch_count=sum(
                bool(qrel.direction_conflicts)
                for qrel in before_qrels
                if qrel is not None
            ),
            after_known_mismatch_count=sum(
                cls._has_mismatch(qrel, judgment)
                for qrel, judgment in zip(
                    after_qrels,
                    after_judgments,
                    strict=True,
                )
            ),
            after_unjudged_count=sum(
                qrel is None and judgment is None
                for qrel, judgment in zip(
                    after_qrels,
                    after_judgments,
                    strict=True,
                )
            ),
        )

    @classmethod
    def _resolved_grade(
        cls,
        qrel: NiaCaseCorpusRelativeGradedQrel | None,
        judgment: NiaCaseCorpusRelevanceJudgment | None,
    ) -> int | None:
        if qrel is not None:
            return int(qrel.relevance_grade)
        if judgment is not None:
            return int(judgment.relevance_grade)
        return None

    @classmethod
    def _has_mismatch(
        cls,
        qrel: NiaCaseCorpusRelativeGradedQrel | None,
        judgment: NiaCaseCorpusRelevanceJudgment | None,
    ) -> bool:
        if qrel is not None:
            return bool(qrel.direction_conflicts)
        if judgment is not None:
            return bool(judgment.direction_conflicts)
        return False

    @classmethod
    def _load_models(
        cls,
        path: Path,
        model_type: type[CareCompatibilityProbeModel],
    ) -> list[CareCompatibilityProbeModel]:
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    asyncio.run(NiaCaseCareCompatibilityProbeCli.main())
