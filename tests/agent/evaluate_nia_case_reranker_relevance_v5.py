"""기존 Dense Top-40 후보 풀에서 후보 보존형 Case 리랭커를 다시 평가한다."""

import asyncio
from pathlib import Path
from typing import ClassVar, TypeVar

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeGoldenCase,
)
from tests.agent.evaluate_nia_case_corpus_relative_live_v3 import (
    CorpusRelativeLiveEvaluationStatus,
    NiaCaseCorpusRelativeLiveMarkdownReporter,
    NiaCaseCorpusRelativeLiveProbe,
    NiaCaseCorpusRelativeLiveRunSummary,
)
from tests.agent.interactive_two_layer_rag_cli import Utf8ConsoleConfigurator
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
)

RerankerEvaluationModel = TypeVar("RerankerEvaluationModel", bound=RagModel)


class NiaCaseRerankerRelevanceV5Cli:
    """임베딩 검색을 반복하지 않고 변경된 selector와 reranker만 분리 실행한다."""

    RUN_ID: ClassVar[str] = "reranker_relevance_20260926_2150_v1"
    EXPECTED_CORPUS_CASE_COUNT: ClassVar[int] = 3581
    GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v4.jsonl"
    )
    LIVE_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl"
    )
    PROBE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_reranker_relevance_probe_20260926_2150_v1.jsonl"
    )
    UNJUDGED_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_reranker_relevance_unjudged_20260926_2150_v1.jsonl"
    )
    SUMMARY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_reranker_relevance_summary_20260926_2150_v1.jsonl"
    )
    REPORT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_2150_NIA_CASE_RERANKER_RELEVANCE_V5_REPORT.md"
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
        golden_cases = cls._load_models(
            cls.GOLDEN_PATH,
            NiaCaseCorpusRelativeGoldenCase,
        )

        # Dense 검색 결과는 이전 실행과 완전히 같음이 확인됐으므로 로컬 임베딩을 다시 계산하지 않는다.
        probe = await NiaCaseCorpusRelativeLiveProbe().run(
            queries,
            internal_items,
            golden_cases,
        )
        unjudged_count = sum(
            item.candidate_count for item in probe.unjudged_items
        )
        summary = NiaCaseCorpusRelativeLiveRunSummary(
            run_id=cls.RUN_ID,
            golden_version="v4",
            status=(
                CorpusRelativeLiveEvaluationStatus.COMPLETE
                if unjudged_count == 0
                else CorpusRelativeLiveEvaluationStatus.NEEDS_JUDGMENT
            ),
            query_count=len(queries),
            corpus_case_count=cls.EXPECTED_CORPUS_CASE_COUNT,
            dense_model="BAAI/bge-m3",
            reranker_model="BAAI/bge-reranker-v2-m3",
            candidate_count=sum(item.candidate_count for item in internal_items),
            top3_count=sum(len(item.hits) for item in probe.items),
            unjudged_count=unjudged_count,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.PROBE_PATH, list(probe.items))
        writer.write(cls.UNJUDGED_PATH, list(probe.unjudged_items))
        writer.write(cls.SUMMARY_PATH, [summary])
        cls.REPORT_PATH.write_text(
            NiaCaseCorpusRelativeLiveMarkdownReporter().render(
                summary,
                baseline=None,
                live=None,
            ),
            encoding="utf-8",
        )
        print(
            "후보 보존형 리랭커 평가 실행 완료: "
            f"queries={summary.query_count}, top3={summary.top3_count}, "
            f"unjudged={summary.unjudged_count}"
        )

    @classmethod
    def _load_models(
        cls,
        path: Path,
        model_type: type[RerankerEvaluationModel],
    ) -> list[RerankerEvaluationModel]:
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    asyncio.run(NiaCaseRerankerRelevanceV5Cli.main())
