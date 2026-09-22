"""Claim 탐색과 공인 Evidence 검증의 LangGraph 경로를 검증한다."""

from enum import StrEnum

from agent.adapters import (
    FixtureCategoryCode,
    FixtureClaimRetriever,
    FixtureEvidenceRetriever,
    FixtureIngredientRepository,
    FixtureProductRepository,
    FixtureProductTaxonomy,
)
from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.nodes import CLAIM_ONLY_PRODUCT_LIMITATION, EVIDENCE_PRODUCT_LIMITATION
from agent.ports import IngredientRepository, LlmClient, ProductRepository
from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.claim_schemas import (
    ClaimIngredientMatchingStatus,
    ClaimIngredientRef,
    ClaimSearchRequest,
    ClaimSearchResult,
)
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.ports import ClaimRetriever, EvidenceRetriever, EvidenceStatementGenerator
from agent.rag.schemas import (
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    EvidenceStatementGenerationRequest,
    GeneratedEvidenceStatement,
    GeneratedEvidenceStatements,
    IngredientResolveRequest,
    IngredientResolveResult,
    LocalEmbeddingModel,
    LookupStatus,
    ProductCandidateSet,
    ProductCategory,
    ProductGetRequest,
    ProductGetResult,
    ProductRecord,
    ProductSearchRequest,
    ProductSearchResult,
    QuestionIntent,
    RagConfidenceTier,
    RagDocument,
    RagDocumentField,
    RetrievedChunk,
)
from agent.schemas import (
    AuthenticatedChatContext,
    ChatServiceRequest,
    ChatStatus,
    ChatTurnInput,
    ErrorCode,
    Intent,
    ParsedRequest,
    RagRoute,
    RegisterRoomRequest,
    UnderstandingRequest,
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


class MixedClaimRetriever(ClaimRetriever):
    def __init__(self, calls: list[WorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureClaimRetriever()

    @property
    def embedding_model(self) -> LocalEmbeddingModel:
        return LocalEmbeddingModel.BGE_M3

    async def search(self, request: ClaimSearchRequest) -> ClaimSearchResult:
        self._calls.append(WorkflowCall.CLAIM)
        result = await self._delegate.search(request)
        first = result.hits[0]
        retinol = first.model_copy(
            deep=True,
            update={
                "claim_chunk_id": "fixture-claim-chunk-retinol-1",
                "statement_id": "fixture-claim-retinol-1",
                "content": "유사한 피부 고민 사례에서 레티놀이 언급되었습니다.",
                "ingredient_refs": [
                    ClaimIngredientRef(
                        raw_name="레티놀",
                        ingredient_id="ingredient:retinol",
                        matching_status=ClaimIngredientMatchingStatus.MATCHED,
                    )
                ],
            },
        )
        return result.model_copy(deep=True, update={"hits": [first, retinol]})


class UnresolvedClaimRetriever(ClaimRetriever):
    """Data가 확정하지 않은 raw_name을 Agent가 다시 매칭하지 않는지 확인한다."""

    def __init__(self, calls: list[WorkflowCall]) -> None:
        self._calls = calls
        self._delegate = FixtureClaimRetriever()

    @property
    def embedding_model(self) -> LocalEmbeddingModel:
        return LocalEmbeddingModel.BGE_M3

    async def search(self, request: ClaimSearchRequest) -> ClaimSearchResult:
        self._calls.append(WorkflowCall.CLAIM)
        result = await self._delegate.search(request)
        first = result.hits[0]
        unresolved = first.model_copy(
            deep=True,
            update={
                "claim_chunk_id": "fixture-claim-chunk-unresolved-1",
                "statement_id": "fixture-claim-unresolved-1",
                "ingredient_refs": [
                    ClaimIngredientRef(
                        raw_name="UNKNOWN EXTRACT",
                        ingredient_id=None,
                        matching_status=ClaimIngredientMatchingStatus.UNRESOLVED,
                    )
                ],
            },
        )
        return result.model_copy(deep=True, update={"hits": [unresolved]})


class VerifiedEvidenceRetriever(EvidenceRetriever):
    def __init__(self, calls: list[WorkflowCall]) -> None:
        self._calls = calls
        document = RagDocument(
            evidence=EvidenceRecord(
                evidence_id="evidence:verified-niacinamide",
                source_id="pubmed:verified-niacinamide",
                source_title="검증된 나이아신아마이드 논문",
                document_version="v1",
                text="나이아신아마이드 관련 검증 가능한 근거입니다.",
                locator="abstract",
                target_ids=["ingredient:niacinamide"],
                review_status=EvidenceReviewStatus.VERIFIED,
                is_demo=False,
            ),
            fields=[
                RagDocumentField(
                    field_id="efficacy",
                    content="나이아신아마이드 효능 근거",
                    intents=[QuestionIntent.EFFICACY],
                )
            ],
            confidence_tier=RagConfidenceTier.STRUCTURED_KNOWLEDGE,
        )
        self._record = document.evidence
        self._chunks = [
            RetrievedChunk(chunk=draft, vector_similarity=0.9)
            for draft in FieldChunker().chunk(document)
        ]

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        self._calls.append(WorkflowCall.EVIDENCE)
        if "ingredient:niacinamide" not in request.target_ids:
            return EvidenceSearchResult(status=LookupStatus.NO_RESULTS)
        return EvidenceSearchResult(
            status=LookupStatus.SUCCESS,
            records=[self._record],
            chunks=self._chunks,
        )


class EchoEvidenceStatementGenerator(EvidenceStatementGenerator):
    async def generate(
        self,
        request: EvidenceStatementGenerationRequest,
    ) -> GeneratedEvidenceStatements:
        return GeneratedEvidenceStatements(
            claims=[
                GeneratedEvidenceStatement(
                    sentence=record.text,
                    evidence_ids=[record.evidence_id],
                )
                for record in request.records
            ]
        )


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


class OverlappingProductRepository(ProductRepository):
    """서로 다른 추천 성분 조회가 같은 상품을 반환하는 병합 경계를 재현한다."""

    def __init__(self, calls: list[WorkflowCall]) -> None:
        self._calls = calls
        taxonomy = FixtureProductTaxonomy()
        self._product = ProductRecord(
            product_id="product:shared-serum",
            version="fixture-v1",
            name="공통 성분 세럼",
            category=taxonomy.category(FixtureCategoryCode.SERUM),
            texture=taxonomy.SERUM,
            ingredient_ids=["ingredient:niacinamide", "ingredient:retinol"],
            source_id="fixture-overlapping-product",
            checked_at="2026-09-17T00:00:00Z",
            is_demo=False,
        )

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        self._calls.append(WorkflowCall.PRODUCT)
        if not request.filters.ingredient_ids:
            return ProductSearchResult(status=LookupStatus.NO_RESULTS)
        return ProductSearchResult(
            status=LookupStatus.SUCCESS,
            products=[self._product.model_copy(deep=True)],
        )

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        if request.product_id == self._product.product_id:
            return ProductGetResult(
                status=LookupStatus.SUCCESS,
                product=self._product.model_copy(deep=True),
            )
        return ProductGetResult(status=LookupStatus.NO_RESULTS)


class FixedRequestLlm(LlmClient):
    def __init__(self, parsed_request: ParsedRequest) -> None:
        self._parsed_request = parsed_request

    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        return self._parsed_request.model_copy(deep=True)


class TwoLayerRagHarness:
    def create(
        self,
        calls: list[WorkflowCall],
        claim_failure: bool = False,
        evidence_no_results: bool = False,
        llm: LlmClient | None = None,
        claim_retriever: ClaimRetriever | None = None,
        evidence_retriever: EvidenceRetriever | None = None,
        answer_generator: AnswerGenerator | None = None,
        product_repository: ProductRepository | None = None,
    ) -> DevelopmentAgentApplication:
        application = DevelopmentAgentFactory(
            llm=llm,
            claim_retriever=(
                claim_retriever
                or TrackingClaimRetriever(calls, fail=claim_failure)
            ),
            evidence_retriever=(
                evidence_retriever
                or TrackingEvidenceRetriever(calls, no_results=evidence_no_results)
            ),
            answer_generator=answer_generator,
            ingredient_repository=TrackingIngredientRepository(calls),
            product_repository=product_repository or TrackingProductRepository(calls),
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
    async def test_same_product_from_supported_and_claim_only_is_merged(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(
            calls,
            claim_retriever=MixedClaimRetriever(calls),
            evidence_retriever=VerifiedEvidenceRetriever(calls),
            answer_generator=AnswerGenerator(EchoEvidenceStatementGenerator()),
            product_repository=OverlappingProductRepository(calls),
        )

        output = await application.service.handle_turn(
            harness.request("overlapping-product-1", "피지가 많고 좁쌀이 나는데 세럼 추천해줘")
        )

        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        assert calls == [
            WorkflowCall.CLAIM,
            WorkflowCall.EVIDENCE,
            WorkflowCall.EVIDENCE,
            WorkflowCall.PRODUCT,
            WorkflowCall.PRODUCT,
        ]
        assert len(candidate_set.candidates) == 1
        candidate = candidate_set.candidates[0]
        assert candidate.product.product_id == "product:shared-serum"
        assert "공인 Evidence가 확인된 성분 포함: ingredient:niacinamide" in (
            candidate.reasons
        )
        assert "Claim 기반 성분 포함: ingredient:retinol" in (
            candidate.reasons
        )
        assert EVIDENCE_PRODUCT_LIMITATION in candidate.unresolved
        assert CLAIM_ONLY_PRODUCT_LIMITATION in candidate.unresolved
        assert [citation.evidence_id for citation in output.citations] == [
            "evidence:verified-niacinamide"
        ]

    async def test_same_product_from_multiple_claim_only_ingredients_is_merged(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(
            calls,
            claim_retriever=MixedClaimRetriever(calls),
            evidence_no_results=True,
            product_repository=OverlappingProductRepository(calls),
        )

        output = await application.service.handle_turn(
            harness.request("overlapping-claim-only-1", "피지가 많고 좁쌀이 나는데 세럼 추천해줘")
        )

        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        assert calls == [
            WorkflowCall.CLAIM,
            WorkflowCall.EVIDENCE,
            WorkflowCall.EVIDENCE,
            WorkflowCall.PRODUCT,
            WorkflowCall.PRODUCT,
        ]
        assert len(candidate_set.candidates) == 1
        candidate = candidate_set.candidates[0]
        assert candidate.product.product_id == "product:shared-serum"
        assert "Claim 기반 성분 포함: ingredient:niacinamide" in (
            candidate.reasons
        )
        assert "Claim 기반 성분 포함: ingredient:retinol" in (
            candidate.reasons
        )
        assert EVIDENCE_PRODUCT_LIMITATION not in candidate.unresolved
        assert CLAIM_ONLY_PRODUCT_LIMITATION in candidate.unresolved
        assert output.citations == []

    async def test_supported_and_claim_only_products_are_grouped_and_ordered(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(
            calls,
            claim_retriever=MixedClaimRetriever(calls),
            evidence_retriever=VerifiedEvidenceRetriever(calls),
            answer_generator=AnswerGenerator(EchoEvidenceStatementGenerator()),
        )

        output = await application.service.handle_turn(
            harness.request("mixed-evidence-1", "피지가 많고 좁쌀이 나는데 세럼 추천해줘")
        )

        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        assert output.status is ChatStatus.PARTIAL
        assert calls == [
            WorkflowCall.CLAIM,
            WorkflowCall.EVIDENCE,
            WorkflowCall.EVIDENCE,
            WorkflowCall.PRODUCT,
            WorkflowCall.PRODUCT,
        ]
        assert [candidate.product.product_id for candidate in candidate_set.candidates] == [
            "product:niacinamide-serum",
            "product:retinol-serum",
        ]
        assert "공인 근거가 확인된 성분 기반 제품 후보" in output.message
        assert "Claim 기반 제품 후보" in output.message
        assert [citation.evidence_id for citation in output.citations] == [
            "evidence:verified-niacinamide"
        ]
        assert CLAIM_ONLY_PRODUCT_LIMITATION in candidate_set.candidates[1].unresolved

    async def test_rule_routes_concern_to_claim_when_llm_omits_route(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        llm = FixedRequestLlm(
            ParsedRequest(
                intents=[Intent.PRODUCT_DISCOVERY],
                query="피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?",
                skin_concerns=["피지", "좁쌀 여드름"],
            )
        )
        application = harness.create(calls, llm=llm)

        output = await application.service.handle_turn(
            harness.request("rule-concern-1", "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?")
        )

        assert output.status is ChatStatus.PARTIAL
        assert calls == [WorkflowCall.CLAIM, WorkflowCall.EVIDENCE, WorkflowCall.PRODUCT]

    async def test_rule_corrects_misclassified_concern_discovery_intent(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        llm = FixedRequestLlm(
            ParsedRequest(
                intents=[Intent.EVIDENCE_QA],
                query="피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?",
                skin_concerns=["피지", "좁쌀 여드름"],
                rag_route=RagRoute.EVIDENCE_ONLY,
            )
        )
        application = harness.create(calls, llm=llm, evidence_no_results=True)

        output = await application.service.handle_turn(
            harness.request(
                "rule-misclassified-concern-1",
                "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?",
            )
        )

        assert output.status is ChatStatus.PARTIAL
        assert output.intents == [Intent.PRODUCT_DISCOVERY]
        assert calls == [WorkflowCall.CLAIM, WorkflowCall.EVIDENCE, WorkflowCall.PRODUCT]
        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        assert candidate_set.candidates
        assert CLAIM_ONLY_PRODUCT_LIMITATION in candidate_set.candidates[0].unresolved
        assert output.citations == []

    async def test_rule_keeps_concern_explanation_as_evidence_question(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        llm = FixedRequestLlm(
            ParsedRequest(
                intents=[Intent.EVIDENCE_QA],
                query="피지가 많은 원인이 뭐야?",
                skin_concerns=["피지"],
                rag_route=RagRoute.EVIDENCE_ONLY,
            )
        )
        application = harness.create(calls, llm=llm)

        output = await application.service.handle_turn(
            harness.request("rule-concern-evidence-1", "피지가 많은 원인이 뭐야?")
        )

        assert output.intents == [Intent.EVIDENCE_QA]
        assert WorkflowCall.CLAIM not in calls
        assert WorkflowCall.PRODUCT not in calls
        assert calls == [WorkflowCall.INGREDIENT, WorkflowCall.EVIDENCE]

    async def test_rule_skips_rag_for_explicit_ingredient_product_query(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        llm = FixedRequestLlm(
            ParsedRequest(
                intents=[Intent.PRODUCT_DISCOVERY],
                query="나이아신아마이드 세럼 추천해줘",
                ingredient_mentions=["나이아신아마이드"],
                rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
            )
        )
        application = harness.create(calls, llm=llm)

        output = await application.service.handle_turn(
            harness.request("rule-ingredient-1", "나이아신아마이드 세럼 추천해줘")
        )

        assert output.status is ChatStatus.COMPLETED
        assert calls == [WorkflowCall.INGREDIENT, WorkflowCall.PRODUCT]

    async def test_rule_skips_claim_for_product_filter_only_query(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        llm = FixedRequestLlm(
            ParsedRequest(
                intents=[Intent.PRODUCT_DISCOVERY],
                query="세럼 추천해줘",
                category=ProductCategory(code="demo:serum", name="세럼"),
            )
        )
        application = harness.create(calls, llm=llm)

        output = await application.service.handle_turn(
            harness.request("rule-filter-1", "세럼 추천해줘")
        )

        assert output.status is ChatStatus.COMPLETED
        assert calls == [WorkflowCall.PRODUCT]

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

        assert output.status is ChatStatus.PARTIAL
        assert calls == [WorkflowCall.CLAIM, WorkflowCall.EVIDENCE, WorkflowCall.PRODUCT]
        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        assert candidate_set.candidates[0].product.product_id == "product:niacinamide-serum"
        assert CLAIM_ONLY_PRODUCT_LIMITATION in candidate_set.candidates[0].unresolved
        assert output.citations == []

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
        assert calls == [WorkflowCall.CLAIM, WorkflowCall.EVIDENCE, WorkflowCall.PRODUCT]
        assert any(item.kind is UnresolvedKind.NO_EVIDENCE for item in output.unresolved)
        assert any(isinstance(artifact, ProductCandidateSet) for artifact in output.artifacts)
        assert output.citations == []

    async def test_unresolved_claim_ingredient_is_not_resolved_again(self) -> None:
        calls: list[WorkflowCall] = []
        harness = TwoLayerRagHarness()
        application = harness.create(
            calls,
            claim_retriever=UnresolvedClaimRetriever(calls),
        )

        output = await application.service.handle_turn(
            harness.request("unresolved-claim-1", "피지가 많은데 세럼 추천해줘")
        )

        assert calls == [WorkflowCall.CLAIM]
        assert WorkflowCall.INGREDIENT not in calls
        assert WorkflowCall.EVIDENCE not in calls
        assert any("UNKNOWN EXTRACT" in item.detail for item in output.unresolved)

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
