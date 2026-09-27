"""동일한 후보 풀에서 NIA Case 리랭커의 실행 재현성을 확인한다."""

import asyncio
from pathlib import Path
from typing import ClassVar

from pydantic import Field

from agent.rag.case_schemas import DEFAULT_CASE_CANDIDATE_LIMIT
from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeGoldenCase,
)
from tests.agent.evaluate_nia_case_corpus_relative_live_v3 import (
    NiaCaseCorpusRelativeLiveProbe,
    NiaCaseCorpusRelativeLiveProbeItem,
)
from tests.agent.interactive_two_layer_rag_cli import Utf8ConsoleConfigurator
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
    InternalCandidatePoolItem,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
)


class NiaCaseRerankerRepeatComparison(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    ordered_top3_match: bool
    membership_top3_match: bool
    first_case_ids: list[str] = Field(min_length=3, max_length=3)
    repeat_case_ids: list[str] = Field(min_length=3, max_length=3)


class NiaCaseRerankerRepeatSummary(RagModel):
    run_id: str = Field(min_length=1)
    query_count: int = Field(ge=1)
    ordered_top3_match_count: int = Field(ge=0)
    membership_top3_match_count: int = Field(ge=0)
    unjudged_count: int = Field(ge=0)
    comparisons: list[NiaCaseRerankerRepeatComparison] = Field(min_length=1)


class NiaCaseDenseBaselineComparison(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    ordered_top40_match: bool
    membership_top40_match: bool


class NiaCaseDenseBaselineSummary(RagModel):
    query_count: int = Field(ge=1)
    ordered_top40_match_count: int = Field(ge=0)
    membership_top40_match_count: int = Field(ge=0)
    comparisons: list[NiaCaseDenseBaselineComparison] = Field(min_length=1)


class NiaCaseDenseBaselineChecker:
    """과거 후보 풀과 Live 후보 풀의 dense Top-40을 직접 비교한다."""

    def compare(
        self,
        baseline_items: list[InternalCandidatePoolItem],
        live_items: list[InternalCandidatePoolItem],
    ) -> NiaCaseDenseBaselineSummary:
        baseline_by_id = {item.evaluation_id: item for item in baseline_items}
        live_by_id = {item.evaluation_id: item for item in live_items}
        if set(baseline_by_id) != set(live_by_id):
            raise RuntimeError(
                "Dense 기준선과 Live 실행의 질의 집합이 다릅니다: "
                f"baseline_only={sorted(set(baseline_by_id) - set(live_by_id))}, "
                f"live_only={sorted(set(live_by_id) - set(baseline_by_id))}"
            )

        comparisons: list[NiaCaseDenseBaselineComparison] = []
        for evaluation_id in sorted(baseline_by_id):
            baseline_case_ids = self._dense_case_ids(baseline_by_id[evaluation_id])
            live_case_ids = self._dense_case_ids(live_by_id[evaluation_id])
            comparisons.append(
                NiaCaseDenseBaselineComparison(
                    evaluation_id=evaluation_id,
                    ordered_top40_match=baseline_case_ids == live_case_ids,
                    membership_top40_match=(
                        set(baseline_case_ids) == set(live_case_ids)
                    ),
                )
            )
        return NiaCaseDenseBaselineSummary(
            query_count=len(comparisons),
            ordered_top40_match_count=sum(
                item.ordered_top40_match for item in comparisons
            ),
            membership_top40_match_count=sum(
                item.membership_top40_match for item in comparisons
            ),
            comparisons=comparisons,
        )

    def _dense_case_ids(self, item: InternalCandidatePoolItem) -> list[str]:
        return [
            candidate.case_id
            for candidate in sorted(
                (
                    candidate
                    for candidate in item.candidates
                    if candidate.dense_rank is not None
                    and candidate.dense_rank <= DEFAULT_CASE_CANDIDATE_LIMIT
                ),
                key=lambda candidate: candidate.dense_rank
                or DEFAULT_CASE_CANDIDATE_LIMIT,
            )
        ]


class NiaCaseRerankerRepeatChecker:
    """첫 Live 결과와 반복 실행 결과를 순서와 구성으로 나누어 비교한다."""

    def compare(
        self,
        run_id: str,
        first_items: list[NiaCaseCorpusRelativeLiveProbeItem],
        repeat_items: list[NiaCaseCorpusRelativeLiveProbeItem],
        unjudged_count: int,
    ) -> NiaCaseRerankerRepeatSummary:
        first_by_id = {item.evaluation_id: item for item in first_items}
        repeat_by_id = {item.evaluation_id: item for item in repeat_items}
        if set(first_by_id) != set(repeat_by_id):
            raise RuntimeError(
                "리랭커 반복 실행의 질의 집합이 첫 Live 실행과 다릅니다: "
                f"first_only={sorted(set(first_by_id) - set(repeat_by_id))}, "
                f"repeat_only={sorted(set(repeat_by_id) - set(first_by_id))}"
            )

        comparisons: list[NiaCaseRerankerRepeatComparison] = []
        for evaluation_id in sorted(first_by_id):
            first_case_ids = [hit.case_id for hit in first_by_id[evaluation_id].hits]
            repeat_case_ids = [hit.case_id for hit in repeat_by_id[evaluation_id].hits]
            comparisons.append(
                NiaCaseRerankerRepeatComparison(
                    evaluation_id=evaluation_id,
                    ordered_top3_match=first_case_ids == repeat_case_ids,
                    membership_top3_match=set(first_case_ids) == set(repeat_case_ids),
                    first_case_ids=first_case_ids,
                    repeat_case_ids=repeat_case_ids,
                )
            )
        return NiaCaseRerankerRepeatSummary(
            run_id=run_id,
            query_count=len(comparisons),
            ordered_top3_match_count=sum(
                item.ordered_top3_match for item in comparisons
            ),
            membership_top3_match_count=sum(
                item.membership_top3_match for item in comparisons
            ),
            unjudged_count=unjudged_count,
            comparisons=comparisons,
        )


class NiaCaseCorpusRelativeLiveRerankerRecheckCli:
    RUN_ID: ClassVar[str] = "live_20260926_1416_v1_repeat_1"
    GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v4.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )
    BASELINE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    FIRST_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_probe_20260926_1416_v1.jsonl"
    )
    REPEAT_PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_probe_repeat_20260926_1416_v1.jsonl"
    )
    REPEAT_SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_reranker_repeat_summary_20260926_1416_v1.jsonl"
    )
    DENSE_SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_dense_baseline_summary_20260926_1416_v1.jsonl"
    )

    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        queries = NiaCaseSemanticEvaluationQueryLoader().load(
            NiaCaseCorpusRelativeEvaluationCli.QUERY_PATH
        ).items
        internal_items = CandidatePoolArtifactLoader().load_internal(
            cls.LIVE_POOL_PATH
        )
        query_ids = {item.evaluation_id for item in queries}
        baseline_items = [
            item
            for item in CandidatePoolArtifactLoader().load_internal(
                cls.BASELINE_POOL_PATH
            )
            if item.evaluation_id in query_ids
        ]
        golden_cases = cls._load_golden(cls.GOLDEN_PATH)
        first_items = cls._load_probe(cls.FIRST_PROBE_PATH)

        # Dense 검색을 다시 수행하지 않아 리랭커 자체의 재현성만 분리해 확인한다.
        repeat = await NiaCaseCorpusRelativeLiveProbe().run(
            queries,
            internal_items,
            golden_cases,
        )
        unjudged_count = sum(
            item.candidate_count for item in repeat.unjudged_items
        )
        summary = NiaCaseRerankerRepeatChecker().compare(
            run_id=cls.RUN_ID,
            first_items=first_items,
            repeat_items=repeat.items,
            unjudged_count=unjudged_count,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.REPEAT_PROBE_PATH, list(repeat.items))
        writer.write(cls.REPEAT_SUMMARY_PATH, [summary])
        dense_summary = NiaCaseDenseBaselineChecker().compare(
            baseline_items,
            internal_items,
        )
        writer.write(cls.DENSE_SUMMARY_PATH, [dense_summary])
        print(
            "리랭커 반복 실행 완료: "
            f"ordered_top3={summary.ordered_top3_match_count}/{summary.query_count}, "
            "membership_top3="
            f"{summary.membership_top3_match_count}/{summary.query_count}, "
            f"unjudged={summary.unjudged_count}"
        )
        print(
            "Dense 기준선 비교 완료: "
            f"ordered_top40={dense_summary.ordered_top40_match_count}/"
            f"{dense_summary.query_count}, membership_top40="
            f"{dense_summary.membership_top40_match_count}/"
            f"{dense_summary.query_count}"
        )

    @classmethod
    def _load_golden(
        cls,
        path: Path,
    ) -> list[NiaCaseCorpusRelativeGoldenCase]:
        return [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @classmethod
    def _load_probe(
        cls,
        path: Path,
    ) -> list[NiaCaseCorpusRelativeLiveProbeItem]:
        return [
            NiaCaseCorpusRelativeLiveProbeItem.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    asyncio.run(NiaCaseCorpusRelativeLiveRerankerRecheckCli.main())
