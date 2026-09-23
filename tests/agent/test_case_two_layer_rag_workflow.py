from enum import StrEnum

from agent.adapters import (
    FixtureCaseClaimExtractor,
    FixtureCaseEmbedder,
    FixtureCaseReranker,
    FixtureCaseRetriever,
    FixtureEvidenceRetriever,
    FixtureIngredientRepository,
    FixtureProductRepository,
    FixtureProductTaxonomy,
)
from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.ports import IngredientRepository, LlmClient, ProductRepository
from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimExtractionResult,
    CaseClaimType,
    ExtractedCaseClaim,
    ExtractedIngredientMention,
)
from agent.rag.case_schemas import (
    CaseRerankRequest,
    CaseRerankResult,
    CaseSearchRequest,
    CaseSearchResult,
)
from agent.rag.ports import (
    CaseClaimExtractor,
    CaseReranker,
    CaseRetriever,
    EvidenceRetriever,
    TextEmbedder,
)
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IngredientResolveRequest,
    IngredientResolveResult,
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
    Intent,
    IntentQueryPlan,
    ParsedRequest,
    RagRoute,
    RegisterRoomRequest,
    UnderstandingRequest,
)


class CaseWorkflowCall(StrEnum):
    EMBEDDING = "embedding"
    CASE_SEARCH = "case_search"
    CASE_RERANK = "case_rerank"
    CLAIM_EXTRACTION = "claim_extraction"
    INGREDIENT = "ingredient"
    EVIDENCE = "evidence"
    PRODUCT = "product"


class FixedCaseWorkflowLlm(LlmClient):
    def __init__(self, request: ParsedRequest) -> None:
        self._request = request

    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        return self._request.model_copy(deep=True)


class TrackingCaseEmbedder(TextEmbedder):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureCaseEmbedder()

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self._calls.append(CaseWorkflowCall.EMBEDDING)
        return await self._delegate.embed(request)


class TrackingCaseRetriever(CaseRetriever):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureCaseRetriever()
        self.requests: list[CaseSearchRequest] = []

    async def search(self, request: CaseSearchRequest) -> CaseSearchResult:
        self._calls.append(CaseWorkflowCall.CASE_SEARCH)
        self.requests.append(request.model_copy(deep=True))
        return await self._delegate.search(request)


class TrackingCaseReranker(CaseReranker):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureCaseReranker()
        self.requests: list[CaseRerankRequest] = []

    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        self._calls.append(CaseWorkflowCall.CASE_RERANK)
        self.requests.append(request.model_copy(deep=True))
        return await self._delegate.rerank(request)


class FailingCaseReranker(CaseReranker):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls

    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        self._calls.append(CaseWorkflowCall.CASE_RERANK)
        raise RuntimeError("reranker fallback 테스트")


class TrackingCaseClaimExtractor(CaseClaimExtractor):
    def __init__(self, calls: list[CaseWorkflowCall], invalid_quote: bool = False) -> None:
        self._calls = calls
        self._invalid_quote = invalid_quote
        self._delegate = FixtureCaseClaimExtractor()
        self.requests: list[CaseClaimExtractionRequest] = []

    async def extract(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionResult:
        self._calls.append(CaseWorkflowCall.CLAIM_EXTRACTION)
        self.requests.append(request.model_copy(deep=True))
        if not self._invalid_quote:
            return await self._delegate.extract(request)
        return CaseClaimExtractionResult(
            status=LookupStatus.SUCCESS,
            model="invalid-quote-test",
            claims=[
                ExtractedCaseClaim(
                    case_id=request.cases[0].case_id,
                    claim_type=CaseClaimType.INGREDIENT_EFFECT,
                    ingredients=[
                        ExtractedIngredientMention(raw_name="나이아신아마이드")
                    ],
                    source_quote="원문에 없는 나이아신아마이드 효능 문장입니다.",
                )
            ],
        )


class FailingCaseClaimExtractor(CaseClaimExtractor):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls

    async def extract(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionResult:
        self._calls.append(CaseWorkflowCall.CLAIM_EXTRACTION)
        return CaseClaimExtractionResult(
            status=LookupStatus.ERROR,
            model="failing-claim-extractor",
            error_message="Claim 추출 실패 테스트",
        )


class TrackingCaseIngredientRepository(IngredientRepository):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureIngredientRepository()

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        self._calls.append(CaseWorkflowCall.INGREDIENT)
        return await self._delegate.resolve(request)


class UnresolvedCaseIngredientRepository(IngredientRepository):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        self._calls.append(CaseWorkflowCall.INGREDIENT)
        return IngredientResolveResult(status=LookupStatus.NO_RESULTS)


class TrackingNoResultEvidenceRetriever(EvidenceRetriever):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        self._calls.append(CaseWorkflowCall.EVIDENCE)
        return EvidenceSearchResult(status=LookupStatus.NO_RESULTS)


class TrackingCaseProductRepository(ProductRepository):
    def __init__(self, calls: list[CaseWorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureProductRepository()

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        self._calls.append(CaseWorkflowCall.PRODUCT)
        return await self._delegate.search(request)

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        return await self._delegate.get(request)


class CaseWorkflowHarness:
    def create(
        self,
        calls: list[CaseWorkflowCall],
        *,
        invalid_quote: bool = False,
        llm: LlmClient | None = None,
        evidence_retriever: EvidenceRetriever | None = None,
        case_retriever: CaseRetriever | None = None,
        case_reranker: CaseReranker | None = None,
        case_claim_extractor: CaseClaimExtractor | None = None,
        ingredient_repository: IngredientRepository | None = None,
    ) -> DevelopmentAgentApplication:
        effective_llm = llm or FixedCaseWorkflowLlm(
            ParsedRequest(
                intents=[Intent.PRODUCT_DISCOVERY],
                query="피지가 많고 좁쌀이 나는데 뭘 써야 해?",
                skin_concerns=["피지", "여드름"],
                rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
            )
        )
        app = DevelopmentAgentFactory(
            llm=effective_llm,
            case_embedder=TrackingCaseEmbedder(calls),
            case_retriever=case_retriever or TrackingCaseRetriever(calls),
            case_reranker=case_reranker or TrackingCaseReranker(calls),
            case_claim_extractor=(
                case_claim_extractor
                or TrackingCaseClaimExtractor(calls, invalid_quote)
            ),
            ingredient_repository=(
                ingredient_repository or TrackingCaseIngredientRepository(calls)
            ),
            evidence_retriever=(
                evidence_retriever or TrackingNoResultEvidenceRetriever(calls)
            ),
            product_repository=TrackingCaseProductRepository(calls),
            product_taxonomy=FixtureProductTaxonomy().create(),
        ).create()
        app.history.register_room(
            RegisterRoomRequest(
                actor_id="user-a",
                chat_room_id="room-a",
                thread_id="thread-a",
            )
        )
        return app

    def request(self, request_id: str, message: str) -> ChatServiceRequest:
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(actor_id="user-a", chat_room_id="room-a"),
            turn=ChatTurnInput(
                chat_room_id="room-a",
                request_id=request_id,
                message=message,
            ),
        )


class TestCaseTwoLayerRagWorkflow:
    async def test_복합_요청의_Case_전용_질의를_검색_리랭크_성분선별에_공통_사용한다(
        self,
    ) -> None:
        calls: list[CaseWorkflowCall] = []
        harness = CaseWorkflowHarness()
        case_query = "30대 남성 환절기 여드름 지성 피부에 좋은 성분과 주의사항"
        retriever = TrackingCaseRetriever(calls)
        reranker = TrackingCaseReranker(calls)
        extractor = TrackingCaseClaimExtractor(calls)
        llm = FixedCaseWorkflowLlm(
            ParsedRequest(
                intents=[
                    Intent.PRODUCT_DISCOVERY,
                    Intent.ROUTINE_PLANNING,
                    Intent.EVIDENCE_QA,
                ],
                query="여드름 지성 피부에 좋은 성분과 주의점 및 3일 스킨케어 루틴",
                query_plan=IntentQueryPlan(
                    case_query="여드름 지성 피부에 좋은 성분과 주의사항",
                    evidence_query="여드름 지성 피부 성분의 효능과 주의사항",
                    product_query="검증된 추천 성분을 포함하는 상품",
                    routine_query="추천 상품으로 3일간 스킨케어 루틴 구성",
                ),
                skin_concerns=["여드름", "지성 피부"],
                rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
            )
        )
        app = harness.create(
            calls,
            llm=llm,
            case_retriever=retriever,
            case_reranker=reranker,
            case_claim_extractor=extractor,
        )

        await app.service.handle_turn(
            harness.request(
                "case-query-plan-1",
                (
                    "30대 남성, 요즘 환절기여서 힘들다. 여드름이 자꾸 올라오는 지성 피부인데 "
                    "어떤 성분이 좋고 주의할 점은 뭐야? 추천 상품으로 3일간 스킨케어 루틴 짜줘"
                ),
            )
        )

        assert retriever.requests[0].query == case_query
        assert reranker.requests[0].query == case_query
        assert extractor.requests[0].query == case_query

    async def test_Evidence가_없어도_Case_Claim_상품을_유지한다(self) -> None:
        calls: list[CaseWorkflowCall] = []
        harness = CaseWorkflowHarness()
        app = harness.create(calls)

        output = await app.service.handle_turn(
            harness.request("case-claim-only-1", "피지가 많고 좁쌀이 나는데 뭘 써야 해?")
        )

        candidates = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        assert calls == [
            CaseWorkflowCall.EMBEDDING,
            CaseWorkflowCall.CASE_SEARCH,
            CaseWorkflowCall.CASE_RERANK,
            CaseWorkflowCall.CLAIM_EXTRACTION,
            CaseWorkflowCall.INGREDIENT,
            CaseWorkflowCall.EVIDENCE,
            CaseWorkflowCall.PRODUCT,
        ]
        assert output.status is ChatStatus.PARTIAL
        assert candidates.candidates
        assert "유사 사례에서 질문과 관련해 언급된 성분" in output.message
        assert "역할별 제품 후보" in output.message
        assert "(Claim 기반)" in output.message
        assert "현재 연결된 근거로 충분히 확인하지 못한 후보 성분" in output.message
        assert "case-claim:" not in output.message

    async def test_exact_quote_검증_실패_Claim은_성분과_상품으로_넘기지_않는다(self) -> None:
        calls: list[CaseWorkflowCall] = []
        harness = CaseWorkflowHarness()
        app = harness.create(calls, invalid_quote=True)

        output = await app.service.handle_turn(
            harness.request("invalid-case-claim-1", "피지가 많고 좁쌀이 나는데 뭘 써야 해?")
        )

        assert calls == [
            CaseWorkflowCall.EMBEDDING,
            CaseWorkflowCall.CASE_SEARCH,
            CaseWorkflowCall.CASE_RERANK,
            CaseWorkflowCall.CLAIM_EXTRACTION,
        ]
        assert output.status is ChatStatus.PARTIAL
        assert "사례 기반 성분을 찾지 못했습니다" in output.message

    async def test_명시적_성분_질의는_Case_경로를_건너뛴다(self) -> None:
        calls: list[CaseWorkflowCall] = []
        harness = CaseWorkflowHarness()
        llm = FixedCaseWorkflowLlm(
            ParsedRequest(
                intents=[Intent.EVIDENCE_QA],
                query="나이아신아마이드 효능을 알려줘",
                ingredient_mentions=["나이아신아마이드"],
                rag_route=RagRoute.EVIDENCE_ONLY,
            )
        )
        evidence = FixtureEvidenceRetriever()
        app = harness.create(calls, llm=llm, evidence_retriever=evidence)

        await app.service.handle_turn(
            harness.request("ingredient-evidence-1", "나이아신아마이드 효능을 알려줘")
        )

        assert calls == [CaseWorkflowCall.INGREDIENT]

    async def test_reranker_실패는_벡터_Top3로_fallback한다(self) -> None:
        calls: list[CaseWorkflowCall] = []
        harness = CaseWorkflowHarness()
        app = harness.create(calls, case_reranker=FailingCaseReranker(calls))

        output = await app.service.handle_turn(
            harness.request("case-rerank-fallback-1", "피지가 많고 좁쌀이 나는데 뭘 써야 해?")
        )

        assert CaseWorkflowCall.CLAIM_EXTRACTION in calls
        assert CaseWorkflowCall.EVIDENCE in calls
        assert CaseWorkflowCall.PRODUCT in calls
        assert output.status is ChatStatus.PARTIAL
        assert "벡터 검색 순위 Top-3" in output.message
        assert output.retryable is True

    async def test_Claim_추출_ERROR는_성분_Evidence_상품을_중단한다(self) -> None:
        calls: list[CaseWorkflowCall] = []
        harness = CaseWorkflowHarness()
        app = harness.create(
            calls,
            case_claim_extractor=FailingCaseClaimExtractor(calls),
        )

        output = await app.service.handle_turn(
            harness.request("case-claim-error-1", "피지가 많고 좁쌀이 나는데 뭘 써야 해?")
        )

        assert calls == [
            CaseWorkflowCall.EMBEDDING,
            CaseWorkflowCall.CASE_SEARCH,
            CaseWorkflowCall.CASE_RERANK,
            CaseWorkflowCall.CLAIM_EXTRACTION,
        ]
        assert output.status is ChatStatus.PARTIAL
        assert output.retryable is True
        assert "관련 성분 선별 오류" in output.message

    async def test_unresolved_성분은_Evidence와_상품으로_넘기지_않는다(self) -> None:
        calls: list[CaseWorkflowCall] = []
        harness = CaseWorkflowHarness()
        app = harness.create(
            calls,
            ingredient_repository=UnresolvedCaseIngredientRepository(calls),
        )

        output = await app.service.handle_turn(
            harness.request("case-unresolved-1", "피지가 많고 좁쌀이 나는데 뭘 써야 해?")
        )

        assert calls == [
            CaseWorkflowCall.EMBEDDING,
            CaseWorkflowCall.CASE_SEARCH,
            CaseWorkflowCall.CASE_RERANK,
            CaseWorkflowCall.CLAIM_EXTRACTION,
            CaseWorkflowCall.INGREDIENT,
        ]
        assert output.status is ChatStatus.PARTIAL
        assert "표준 성분을 확정하지 못한 Case 관련 성분" in output.message
