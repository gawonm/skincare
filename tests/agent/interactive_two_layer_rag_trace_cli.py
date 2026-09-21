"""2-Layer RAG의 Case → Claim → Evidence → Product 실제 실행 흐름을 단계별로 출력한다.

실행 예시:
    uv run python -m tests.agent.interactive_two_layer_rag_trace_cli \
        "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"
"""

import asyncio
import sys

from pydantic import BaseModel, ConfigDict, Field

from agent.ports import IngredientRepository, ProductRepository
from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimExtractionResult,
)
from agent.rag.case_schemas import (
    CaseRerankRequest,
    CaseRerankResult,
    CaseSearchRequest,
    CaseSearchResult,
)
from agent.rag.ports import CaseClaimExtractor, CaseReranker, CaseRetriever, EvidenceRetriever
from agent.rag.retrieval.ingredient_alias_mapper import CommonIngredientAliasMapper
from agent.rag.schemas import (
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    ProductGetRequest,
    ProductGetResult,
    ProductSearchRequest,
    ProductSearchResult,
    ProductTaxonomy,
)
from backend.services.two_layer_rag_adapters import TwoLayerProductTaxonomyProvider
from core.database import Database
from tests.agent.interactive_rag_cli import DIVIDER_LINE, AgentTurnResult
from tests.agent.interactive_two_layer_rag_cli import (
    CliDisplayMode,
    ConfiguredDatabaseFactory,
    InteractiveTwoLayerRagCli,
)


class FlowTraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CaseSearchTrace(FlowTraceModel):
    request: CaseSearchRequest
    result: CaseSearchResult | None = None


class CaseRerankTrace(FlowTraceModel):
    request: CaseRerankRequest
    result: CaseRerankResult | None = None


class CaseClaimExtractionTrace(FlowTraceModel):
    request: CaseClaimExtractionRequest
    result: CaseClaimExtractionResult | None = None


class IngredientResolutionTrace(FlowTraceModel):
    request: IngredientResolveRequest
    result: IngredientResolveResult | None = None


class EvidenceSearchTrace(FlowTraceModel):
    request: EvidenceSearchRequest
    result: EvidenceSearchResult | None = None


class ProductSearchTrace(FlowTraceModel):
    request: ProductSearchRequest
    result: ProductSearchResult | None = None


class TwoLayerFlowSnapshot(FlowTraceModel):
    case_searches: list[CaseSearchTrace] = Field(default_factory=list)
    case_reranks: list[CaseRerankTrace] = Field(default_factory=list)
    claim_extractions: list[CaseClaimExtractionTrace] = Field(default_factory=list)
    ingredient_resolutions: list[IngredientResolutionTrace] = Field(default_factory=list)
    evidence_searches: list[EvidenceSearchTrace] = Field(default_factory=list)
    product_searches: list[ProductSearchTrace] = Field(default_factory=list)


class TwoLayerFlowTraceCollector:
    """실제 포트 호출을 재실행하지 않고 한 턴의 단계별 입출력을 보존한다."""

    def __init__(self) -> None:
        self._snapshot = TwoLayerFlowSnapshot()

    def reset(self) -> None:
        self._snapshot = TwoLayerFlowSnapshot()

    def snapshot(self) -> TwoLayerFlowSnapshot:
        return self._snapshot.model_copy(deep=True)

    def case_search(self, request: CaseSearchRequest) -> CaseSearchTrace:
        trace = CaseSearchTrace(request=request.model_copy(deep=True))
        self._snapshot.case_searches.append(trace)
        return trace

    def case_rerank(self, request: CaseRerankRequest) -> CaseRerankTrace:
        trace = CaseRerankTrace(request=request.model_copy(deep=True))
        self._snapshot.case_reranks.append(trace)
        return trace

    def claim_extraction(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionTrace:
        trace = CaseClaimExtractionTrace(request=request.model_copy(deep=True))
        self._snapshot.claim_extractions.append(trace)
        return trace

    def ingredient_resolution(
        self,
        request: IngredientResolveRequest,
    ) -> IngredientResolutionTrace:
        trace = IngredientResolutionTrace(request=request.model_copy(deep=True))
        self._snapshot.ingredient_resolutions.append(trace)
        return trace

    def evidence_search(self, request: EvidenceSearchRequest) -> EvidenceSearchTrace:
        trace = EvidenceSearchTrace(request=request.model_copy(deep=True))
        self._snapshot.evidence_searches.append(trace)
        return trace

    def product_search(self, request: ProductSearchRequest) -> ProductSearchTrace:
        trace = ProductSearchTrace(request=request.model_copy(deep=True))
        self._snapshot.product_searches.append(trace)
        return trace


class RecordingCaseRetriever(CaseRetriever):
    def __init__(self, delegate: CaseRetriever, collector: TwoLayerFlowTraceCollector) -> None:
        self._delegate = delegate
        self._collector = collector

    async def search(self, request: CaseSearchRequest) -> CaseSearchResult:
        trace = self._collector.case_search(request)
        result = await self._delegate.search(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingCaseReranker(CaseReranker):
    def __init__(self, delegate: CaseReranker, collector: TwoLayerFlowTraceCollector) -> None:
        self._delegate = delegate
        self._collector = collector

    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        trace = self._collector.case_rerank(request)
        result = await self._delegate.rerank(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingCaseClaimExtractor(CaseClaimExtractor):
    def __init__(
        self,
        delegate: CaseClaimExtractor,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def extract(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionResult:
        trace = self._collector.claim_extraction(request)
        result = await self._delegate.extract(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingIngredientRepository(IngredientRepository):
    def __init__(
        self,
        delegate: IngredientRepository,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        trace = self._collector.ingredient_resolution(request)
        result = await self._delegate.resolve(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingFlowEvidenceRetriever(EvidenceRetriever):
    def __init__(
        self,
        delegate: EvidenceRetriever,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        trace = self._collector.evidence_search(request)
        result = await self._delegate.search(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingProductRepository(ProductRepository):
    def __init__(
        self,
        delegate: ProductRepository,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        trace = self._collector.product_search(request)
        result = await self._delegate.search(request)
        trace.result = result.model_copy(deep=True)
        return result

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        return await self._delegate.get(request)


class TwoLayerFlowTracePresenter:
    """서로 다른 검색 단계를 같은 '검색' 로그로 오인하지 않게 구분해 출력한다."""

    QUOTE_PREVIEW_LENGTH = 220
    PRODUCT_PREVIEW_LIMIT = 10

    def __init__(self) -> None:
        self._aliases = CommonIngredientAliasMapper()

    def print_turn(
        self,
        trace: TwoLayerFlowSnapshot,
        result: AgentTurnResult,
        user_message: str,
    ) -> None:
        print(f"\n{DIVIDER_LINE}")
        print(f"사용자 질문: {user_message}")
        self._print_case_search(trace)
        self._print_case_rerank(trace)
        self._print_claim_extraction(trace)
        self._print_ingredient_resolution(trace)
        self._print_evidence_search(trace)
        self._print_product_search(trace)
        print("\n[7. Agent 최종 응답]")
        print(result.turn_output.message)
        if result.turn_output.unresolved:
            print("\n[미해결/보류]")
            for item in result.turn_output.unresolved:
                print(f"- {item.kind.value}: {item.detail}")
        print(DIVIDER_LINE)

    def _print_case_search(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[1. NIA Case Document 임베딩 검색]")
        if not snapshot.case_searches:
            print("- 실행되지 않음")
            return
        for trace in snapshot.case_searches:
            print(f"- 검색 질의: {trace.request.query}")
            print(f"- 후보 요청 수: {trace.request.candidate_limit}")
            if trace.result is None:
                print("- 결과 미수신")
                continue
            print(f"- 상태: {trace.result.status.value}, 반환: {len(trace.result.hits)}건")
            for index, hit in enumerate(trace.result.hits, start=1):
                print(
                    f"  {index}. case_id={hit.case_id} "
                    f"vector_similarity={hit.vector_similarity:.4f}"
                )

    def _print_case_rerank(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[2. BGE 리랭커 Top-3 Case]")
        if not snapshot.case_reranks:
            print("- 실행되지 않음")
            return
        for trace in snapshot.case_reranks:
            print(f"- 리랭크 질의: {trace.request.query}")
            print(f"- 입력 후보: {len(trace.request.candidates)}건, 선택 상한: {trace.request.limit}건")
            if trace.result is None:
                print("- 결과 미수신")
                continue
            print(f"- 모델: {trace.result.model}")
            for index, hit in enumerate(trace.result.hits, start=1):
                print(
                    f"  {index}. case_id={hit.case_id} "
                    f"rerank_score={hit.rerank_score:.4f}"
                )

    def _print_claim_extraction(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[3. Top-3 원문 LLM 관련 성분 선별]")
        if not snapshot.claim_extractions:
            print("- 실행되지 않음")
            return
        for trace in snapshot.claim_extractions:
            print(f"- LLM 입력 case_id: {[case.case_id for case in trace.request.cases]}")
            if trace.result is None:
                print("- 결과 미수신")
                continue
            print(
                f"- 상태: {trace.result.status.value}, model={trace.result.model}, "
                f"prompt={trace.result.prompt_version}"
            )
            for index, claim in enumerate(trace.result.claims, start=1):
                ingredients = [item.raw_name for item in claim.ingredients]
                quote = claim.source_quote[: self.QUOTE_PREVIEW_LENGTH]
                print(
                    f"  {index}. case_id={claim.case_id} ingredients={ingredients}"
                )
                print(f"     quote={quote}")

    def _print_ingredient_resolution(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[4. Agent 별칭 처리 및 표준 ingredient_id 확정]")
        claims = [
            claim
            for extraction in snapshot.claim_extractions
            if extraction.result is not None
            for claim in extraction.result.claims
        ]
        if not claims:
            print("- 선별된 관련 성분 없음")
            return
        for claim in claims:
            for ingredient in claim.ingredients:
                request = IngredientResolveRequest(name=ingredient.raw_name)
                mapped = self._aliases.map_request(request)
                ambiguous = self._aliases.is_ambiguous_family(request)
                resolution = self._find_resolution(snapshot, request.name, mapped.name)
                if resolution is None or resolution.result is None:
                    resolved = "ingredient_id 미확정"
                elif resolution.result.ingredient is not None:
                    record = resolution.result.ingredient
                    resolved = f"{record.canonical_name} / {record.ingredient_id}"
                else:
                    resolved = resolution.result.status.value
                policy = "모호한 성분군" if ambiguous else mapped.name
                print(f"- {ingredient.raw_name} → {policy} → {resolved}")

    def _find_resolution(
        self,
        snapshot: TwoLayerFlowSnapshot,
        raw_name: str,
        mapped_name: str,
    ) -> IngredientResolutionTrace | None:
        matches = [
            trace
            for trace in snapshot.ingredient_resolutions
            if trace.request.name in {raw_name, mapped_name}
        ]
        successful = [
            trace
            for trace in matches
            if trace.result is not None and trace.result.status is LookupStatus.SUCCESS
        ]
        return successful[-1] if successful else (matches[-1] if matches else None)

    def _print_evidence_search(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[5. 성분별 Evidence 검색]")
        if not snapshot.evidence_searches:
            print("- 실행되지 않음")
            return
        for index, trace in enumerate(snapshot.evidence_searches, start=1):
            print(f"{index}. Evidence 질의: {trace.request.query}")
            print(f"   ingredient_id: {trace.request.target_ids}")
            print(f"   Claim당 Evidence 반환 상한: {trace.request.limit}건")
            if trace.result is None:
                print("   결과 미수신")
                continue
            print(
                f"   상태: {trace.result.status.value}, "
                f"반환 Evidence: {len(trace.result.chunks)}건"
            )

    def _print_product_search(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[6. 상품 검색]")
        if not snapshot.product_searches:
            print("- 실행되지 않음")
            return
        for index, trace in enumerate(snapshot.product_searches, start=1):
            filters = trace.request.filters
            print(
                f"{index}. ingredient_ids={filters.ingredient_ids}, "
                f"category={filters.category.code if filters.category else None}"
            )
            if trace.result is None:
                print("   결과 미수신")
                continue
            print(f"   상태: {trace.result.status.value}, 반환 상품: {len(trace.result.products)}건")
            for product in trace.result.products[: self.PRODUCT_PREVIEW_LIMIT]:
                print(f"   - {product.name} ({product.category.name})")


class InteractiveTwoLayerRagTraceCli(InteractiveTwoLayerRagCli):
    """실제 DB·모델 실행에 관찰용 포트 래퍼만 추가한 통합 진단 CLI."""

    def __init__(self, database: Database, product_taxonomy: ProductTaxonomy) -> None:
        self._flow_trace = TwoLayerFlowTraceCollector()
        self._flow_presenter = TwoLayerFlowTracePresenter()
        super().__init__(
            display_mode=CliDisplayMode.COMPACT,
            database=database,
            product_taxonomy=product_taxonomy,
        )

    def _configure_case_retriever(self, delegate: CaseRetriever) -> CaseRetriever:
        return RecordingCaseRetriever(delegate, self._flow_trace)

    def _configure_case_reranker(self, delegate: CaseReranker) -> CaseReranker:
        return RecordingCaseReranker(delegate, self._flow_trace)

    def _configure_case_claim_extractor(
        self,
        delegate: CaseClaimExtractor,
    ) -> CaseClaimExtractor:
        return RecordingCaseClaimExtractor(delegate, self._flow_trace)

    def _configure_ingredient_repository(
        self,
        delegate: IngredientRepository,
    ) -> IngredientRepository:
        return RecordingIngredientRepository(delegate, self._flow_trace)

    def _configure_evidence_retriever(
        self,
        delegate: EvidenceRetriever,
    ) -> EvidenceRetriever:
        return RecordingFlowEvidenceRetriever(delegate, self._flow_trace)

    def _configure_product_repository(
        self,
        delegate: ProductRepository,
    ) -> ProductRepository:
        return RecordingProductRepository(delegate, self._flow_trace)

    async def handle_message(self, user_message: str) -> AgentTurnResult:
        self._flow_trace.reset()
        return await super().handle_message(user_message)

    def print_turn(self, result: AgentTurnResult, user_message: str) -> None:
        self._flow_presenter.print_turn(
            self._flow_trace.snapshot(),
            result,
            user_message,
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
