"""Claim 탐색과 공인 Evidence 검증의 LangGraph 경로를 검증한다."""

from enum import StrEnum

from agent.adapters import (
    FixtureClaimRetriever,
    FixtureEvidenceRetriever,
    FixtureIngredientRepository,
    FixtureProductRepository,
    FixtureProductTaxonomy,
)
from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.ports import IngredientRepository, ProductRepository
from agent.rag.claim_schemas import ClaimSearchRequest, ClaimSearchResult
from agent.rag.ports import ClaimRetriever, EvidenceRetriever
from agent.rag.schemas import (
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IngredientResolveRequest,
    IngredientResolveResult,
    LocalEmbeddingModel,
    LookupStatus,
    ProductCandidateSet,
    ProductGetRequest,
    ProductGetResult,
    ProductSearchRequest,
    ProductSearchResult,
)
from agent.schemas import (
    AuthenticatedChatContext,
    ChatServiceRequest,
    ChatStatus,
    ChatTurnInput,
    ErrorCode,
    RegisterRoomRequest,
    UnresolvedKind,
)


class WorkflowCall(StrEnum):
    CLAIM = "claim"
    INGREDIENT = "ingredient"
    EVIDENCE = "evidence"
    PRODUCT = "product"


class TrackingClaimRetriever(ClaimRetriever):
    def __init__(self, calls: list[WorkflowCall], fail: bool = False) -> None:
        self._calls = calls
        self._fail = fail
        self._delegate = FixtureClaimRetriever()

    @property
    def embedding_model(self) -> LocalEmbeddingModel:
        return LocalEmbeddingModel.BGE_M3

    async def search(self, request: ClaimSearchRequest) -> ClaimSearchResult:
        self._calls.append(WorkflowCall.CLAIM)
        if self._fail:
            return ClaimSearchResult(
                status=LookupStatus.ERROR,
                error_message="Claim 검색 실패 테스트",
            )
        return await self._delegate.search(request)


class TrackingEvidenceRetriever(EvidenceRetriever):
    def __init__(self, calls: list[WorkflowCall], no_results: bool = False) -> None:
        self._calls = calls
        self._no_results = no_results
        self._delegate = FixtureEvidenceRetriever()

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        self._calls.append(WorkflowCall.EVIDENCE)
        if self._no_results:
            return EvidenceSearchResult(status=LookupStatus.NO_RESULTS)
        return await self._delegate.search(request)


class TrackingIngredientRepository(IngredientRepository):
    def __init__(self, calls: list[WorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureIngredientRepository()

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        self._calls.append(WorkflowCall.INGREDIENT)
        return await self._delegate.resolve(request)


class TrackingProductRepository(ProductRepository):
    def __init__(self, calls: list[WorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureProductRepository()

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        self._calls.append(WorkflowCall.PRODUCT)
        return await self._delegate.search(request)

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        return await self._delegate.get(request)


class TwoLayerRagHarness:
    def create(
        self,
        calls: list[WorkflowCall],
        claim_failure: bool = False,
        evidence_no_results: bool = False,
    ) -> DevelopmentAgentApplication:
        application = DevelopmentAgentFactory(
            claim_retriever=TrackingClaimRetriever(calls, fail=claim_failure),
            evidence_retriever=TrackingEvidenceRetriever(
                calls,
                no_results=evidence_no_results,
            ),
            ingredient_repository=TrackingIngredientRepository(calls),
            product_repository=TrackingProductRepository(calls),
            product_taxonomy=FixtureProductTaxonomy().create(),
        ).create()
        application.history.register_room(
            RegisterRoomRequest(
                actor_id="user-a",
                chat_room_id="room-a",
                thread_id="thread-a",
            )
        )
        return application

    def request(self, request_id: str, message: str) -> ChatServiceRequest:
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(actor_id="user-a", chat_room_id="room-a"),
            turn=ChatTurnInput(
                chat_room_id="room-a",
                request_id=request_id,
                message=message,
            ),
        )


class TestTwoLayerRagWorkflow:
    async def test_concern_query_runs_claim_then_evidence_then_product(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(calls)

        output = await application.service.handle_turn(
            harness.request(
                "concern-1",
                "피지가 많고 좁쌀 여드름이 나는데 세럼 추천해줘",
            )
        )

        assert output.status is ChatStatus.COMPLETED
        assert calls == [WorkflowCall.CLAIM, WorkflowCall.EVIDENCE, WorkflowCall.PRODUCT]
        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        assert candidate_set.candidates[0].product.product_id == "product:niacinamide-serum"
        assert output.citations
        assert all(citation.evidence_id.startswith("demo-evidence:") for citation in output.citations)

    async def test_explicit_ingredient_skips_claim_search(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(calls)

        output = await application.service.handle_turn(
            harness.request("ingredient-1", "나이아신아마이드 효능과 주의를 알려줘")
        )

        assert output.status is ChatStatus.COMPLETED
        assert WorkflowCall.CLAIM not in calls
        assert calls == [WorkflowCall.INGREDIENT, WorkflowCall.EVIDENCE]

    async def test_claim_is_exploratory_when_evidence_has_no_results(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(calls, evidence_no_results=True)

        output = await application.service.handle_turn(
            harness.request("no-evidence-1", "피지가 많은데 세럼 추천해줘")
        )

        assert output.status is ChatStatus.PARTIAL
        assert calls == [WorkflowCall.CLAIM, WorkflowCall.EVIDENCE]
        assert any(item.kind is UnresolvedKind.NO_EVIDENCE for item in output.unresolved)
        assert output.citations == []

    async def test_claim_failure_stops_evidence_and_product_search(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(calls, claim_failure=True)

        output = await application.service.handle_turn(
            harness.request("claim-error-1", "피지가 많은데 세럼 추천해줘")
        )

        assert output.status is ChatStatus.PARTIAL
        assert calls == [WorkflowCall.CLAIM]
        assert output.error_code is ErrorCode.TOOL_FAILED
