"""2-Layer RAG의 Case → Claim → Evidence → Product 실제 실행 흐름을 단계별로 출력한다.

실행 예시:
    uv run python -m tests.agent.interactive_two_layer_rag_trace_cli \
        "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"
"""

import asyncio
import sys

from agent.rag.schemas import ProductTaxonomy
from backend.services.two_layer_rag_adapters import TwoLayerProductTaxonomyProvider
from core.database import Database
from tests.agent.interactive_rag_cli import AgentTurnResult
from tests.agent.interactive_two_layer_rag_cli import (
    CaseClaimExtractionTrace,
    CaseRerankTrace,
    CaseSearchTrace,
    CliDisplayMode,
    ConfiguredDatabaseFactory,
    EvidenceSearchTrace,
    FlowTraceModel,
    IngredientResolutionTrace,
    InteractiveTwoLayerRagCli,
    ProductSearchTrace,
    RecordingCaseClaimExtractor,
    RecordingCaseReranker,
    RecordingCaseRetriever,
    RecordingFlowEvidenceRetriever,
    RecordingIngredientRepository,
    RecordingProductRepository,
    TwoLayerFlowSnapshot,
    TwoLayerFlowTraceCollector,
    TwoLayerProductRepository,
    VerboseTwoLayerTurnPresenter,
)


class TwoLayerFlowTracePresenter(VerboseTwoLayerTurnPresenter):
    """하위 호환성을 위해 VerboseTwoLayerTurnPresenter를 상속한다."""

    def print_turn(
        self,
        trace: TwoLayerFlowSnapshot,
        result: AgentTurnResult,
        user_message: str,
    ) -> None:
        super().print_turn(trace, result, user_message)


class InteractiveTwoLayerRagTraceCli(InteractiveTwoLayerRagCli):
    """실제 DB·모델 실행에 관찰용 포트 래퍼만 추가한 통합 진단 CLI.

    `InteractiveTwoLayerRagCli`에 기본 통합된 추적 및 Verbose 출력을 활용한다.
    """

    def __init__(self, database: Database, product_taxonomy: ProductTaxonomy) -> None:
        super().__init__(
            display_mode=CliDisplayMode.VERBOSE,
            database=database,
            product_taxonomy=product_taxonomy,
        )

    @classmethod
    async def main(cls) -> None:
        user_message = " ".join(sys.argv[1:]).strip()
        if not user_message:
            raise ValueError("단계별 점검에 사용할 사용자 질문을 명령 인자로 입력해 주세요.")

        database = ConfiguredDatabaseFactory().create()
        cli: InteractiveTwoLayerRagTraceCli | None = None
        try:
            taxonomy = await TwoLayerProductTaxonomyProvider(
                database.session_factory
            ).load()
            cli = cls(database=database, product_taxonomy=taxonomy)
            cli.print_runtime()
            result = await cli.handle_message(user_message)
            cli.print_turn(result, user_message)
        finally:
            if cli is not None:
                await cli.close()
            else:
                await database.dispose()


if __name__ == "__main__":
    asyncio.run(InteractiveTwoLayerRagTraceCli.main())
