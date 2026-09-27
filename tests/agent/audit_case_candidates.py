"""현재 NIA Case 파이프라인의 여러 사용자 질의를 로컬에서 일괄 점검한다."""

import argparse
import asyncio
from collections import Counter
from pathlib import Path

from pydantic import Field

from agent.rag.schemas import RagModel
from core.database import Database
from tests.agent.case_retrieval_recall_eval import (
    CaseRetrievalEvaluationArguments,
    CaseRetrievalGoldenItem,
    CaseRetrievalGoldenSetLoader,
)
from tests.agent.inspect_case_candidates import (
    CaseCandidateInspectionArguments,
    CaseCandidateInspectionPresenter,
    CaseCandidateInspectionResult,
    LocalCaseCandidateInspector,
)
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    Utf8ConsoleConfigurator,
)


class CaseCandidateBatchAuditArguments(RagModel):
    golden_path: Path
    evaluation_id_prefix: str = Field(min_length=1)


class CaseCandidateBatchAuditItem(RagModel):
    golden: CaseRetrievalGoldenItem
    result: CaseCandidateInspectionResult


class CaseCandidateBatchAuditArgumentsParser:
    DEFAULT_GOLDEN_PATH = Path("tests/agent/nia_case_retrieval_golden_24.jsonl")
    DEFAULT_EVALUATION_ID_PREFIX = "holdout_"

    def parse(self) -> CaseCandidateBatchAuditArguments:
        parser = argparse.ArgumentParser(
            description="현재 NIA Case Top-40·선별·Top-3를 여러 질의에서 점검합니다."
        )
        parser.add_argument(
            "--golden",
            type=Path,
            default=self.DEFAULT_GOLDEN_PATH,
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default=self.DEFAULT_EVALUATION_ID_PREFIX,
        )
        parsed = parser.parse_args()
        return CaseCandidateBatchAuditArguments(
            golden_path=parsed.golden,
            evaluation_id_prefix=parsed.prefix,
        )


class LocalCaseCandidateBatchAuditor:
    def __init__(self, database: Database) -> None:
        self._inspector = LocalCaseCandidateInspector(database)

    async def audit(
        self,
        arguments: CaseCandidateBatchAuditArguments,
    ) -> list[CaseCandidateBatchAuditItem]:
        golden_set = CaseRetrievalGoldenSetLoader().load(
            CaseRetrievalEvaluationArguments(golden_path=arguments.golden_path)
        )
        selected = [
            item
            for item in golden_set.items
            if item.evaluation_id.startswith(arguments.evaluation_id_prefix)
        ]
        if not selected:
            raise RuntimeError(
                "NIA Case 일괄 점검 대상이 없습니다: "
                f"prefix={arguments.evaluation_id_prefix}"
            )
        results: list[CaseCandidateBatchAuditItem] = []
        for golden in selected:
            inspection = await self._inspector.inspect(
                CaseCandidateInspectionArguments(
                    query=golden.original_message,
                    skin_concerns=golden.skin_concerns,
                )
            )
            results.append(
                CaseCandidateBatchAuditItem(golden=golden, result=inspection)
            )
        return results


class CaseCandidateBatchAuditPresenter:
    def __init__(self) -> None:
        self._question_presenter = CaseCandidateInspectionPresenter()

    def print(self, items: list[CaseCandidateBatchAuditItem]) -> None:
        for item in items:
            golden = item.golden
            result = item.result
            target_distribution = Counter(
                hit.metadata.target_concern for hit in result.search.hits
            )
            print("\n" + "=" * 100)
            print(f"evaluation_id: {golden.evaluation_id}")
            print(f"query: {golden.original_message}")
            print(f"skin_concerns: {golden.skin_concerns}")
            print(f"Top-40 target 분포: {dict(target_distribution)}")
            print(
                f"직접 일치={result.selection.direct_match_count}, "
                f"리랭커 입력={len(result.selection.candidates)}"
            )
            print("Top-3:")
            for rank, hit in enumerate(result.rerank.hits, start=1):
                metadata = hit.metadata
                print(
                    f"  {rank}. {hit.case_id} | score={hit.rerank_score:.4f} | "
                    f"target={metadata.target_concern} | concerns={metadata.skin_concerns} | "
                    f"profile={metadata.age}세 {metadata.gender} {metadata.skin_type}"
                )
                print(
                    "     question="
                    + self._question_presenter.question(hit.page_content)
                )


class CaseCandidateBatchAuditCli:
    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        arguments = CaseCandidateBatchAuditArgumentsParser().parse()
        database = ConfiguredDatabaseFactory().create()
        try:
            items = await LocalCaseCandidateBatchAuditor(database).audit(arguments)
            CaseCandidateBatchAuditPresenter().print(items)
        finally:
            await database.dispose()


if __name__ == "__main__":
    asyncio.run(CaseCandidateBatchAuditCli.main())
