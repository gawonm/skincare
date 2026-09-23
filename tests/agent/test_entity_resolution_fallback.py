"""외부 API·DB 없이 성분 식별과 실제 그래프의 폴백 경계를 검증한다."""

import pytest

from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.ports import IngredientRepository, LlmClient
from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.ports import EvidenceRetriever
from agent.rag.retrieval.ingredient_alias_mapper import (
    CommonIngredientAliasMapper,
    IngredientAliasEntry,
    IngredientMentionDetectionRequest,
)
from agent.rag.schemas import (
    EvidenceConditions,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IngredientRecord,
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    RetrievedChunk,
)
from agent.schemas import (
    ChatStatus,
    ErrorCode,
    ExecutionLimits,
    Intent,
    ParsedRequest,
    RegisterRoomRequest,
    UnderstandingRequest,
    UnresolvedKind,
)
from tests.agent.test_agent_chat import AgentTestFactory
from tests.agent.test_agent_rag_contract import (
    ContractEvidenceStatementGenerator,
    RagContractFixture,
)


class ScriptedUnderstanding(LlmClient):
    def __init__(self, parsed: ParsedRequest) -> None:
        self.parsed = parsed

    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        return self.parsed.model_copy(deep=True)


class RecordingIngredients(IngredientRepository):
    def __init__(self) -> None:
        self.results: dict[str, IngredientResolveResult] = {}
        self.requests: list[IngredientResolveRequest] = []

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        self.requests.append(request.model_copy(deep=True))
        return self.results.get(
            request.name, IngredientResolveResult(status=LookupStatus.NO_RESULTS)
        ).model_copy(deep=True)

    def register(self, name: str, ingredient_id: str) -> None:
        self.results[name] = IngredientResolveResult(
            status=LookupStatus.SUCCESS,
            ingredient=IngredientRecord(
                ingredient_id=ingredient_id, canonical_name=name, is_demo=False
            ),
        )


class RecordingSearch(EvidenceRetriever):
    def __init__(self) -> None:
        self.requests: list[EvidenceSearchRequest] = []
        self.result = EvidenceSearchResult(status=LookupStatus.NO_RESULTS)

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        self.requests.append(request.model_copy(deep=True))
        return self.result.model_copy(deep=True)


class FallbackScenario:
    def __init__(self) -> None:
        self.llm = ScriptedUnderstanding(
            ParsedRequest(
                intents=[Intent.EVIDENCE_QA],
                query="나이아신아마이드와 비타민C의 효능",
                ingredient_mentions=["나이아신아마이드", "비타민C"],
            )
        )
        self.ingredients = RecordingIngredients()
        self.ingredients.register("나이아신아마이드", "test:niacinamide")
        self.search = RecordingSearch()
        self.claims = ContractEvidenceStatementGenerator()

    def create(self, limits: ExecutionLimits | None = None) -> DevelopmentAgentApplication:
        app = DevelopmentAgentFactory(
            llm=self.llm,
            ingredient_repository=self.ingredients,
            evidence_retriever=self.search,
            answer_generator=AnswerGenerator(self.claims),
            execution_limits=limits,
        ).create()
        app.history.register_room(
            RegisterRoomRequest(actor_id="user-a", chat_room_id="room-a", thread_id="thread-a")
        )
        return app

    def evidence(self, review: EvidenceReviewStatus = EvidenceReviewStatus.VERIFIED) -> None:
        document = RagContractFixture().document("test:niacinamide")
        document.evidence.review_status = review
        self.search.result = EvidenceSearchResult(
            status=LookupStatus.SUCCESS,
            records=[document.evidence],
            chunks=[
                RetrievedChunk(chunk=draft, vector_similarity=0.9)
                for draft in FieldChunker().chunk(document)
            ],
        )


class TestIngredientAliases:
    @pytest.mark.parametrize("name", ["비타민C", " 비타민 C ", "VITAMIN C", "ｖｉｔａｍｉｎ Ｃ"])
    def test_normalizes_confirmed_whole_term(self, name: str) -> None:
        request = IngredientResolveRequest(name=name)
        mapped = CommonIngredientAliasMapper().map_request(request)
        assert mapped.name == "아스코빅애씨드"
        assert request.name == name

    @pytest.mark.parametrize(
        "name", ["AHA", "시카", "비타민B3", "비타민B5", "히알루론산", "비타민C 유도체"]
    )
    def test_does_not_collapse_families_or_derivatives(self, name: str) -> None:
        request = IngredientResolveRequest(name=name)
        assert CommonIngredientAliasMapper().map_request(request) == request

    @pytest.mark.parametrize(
        "name",
        [
            "살리실산",
            "살리실산(BHA)",
            "BHA(살리실산)",
            " 살리실산 ( BHA ) ",
            "SALICYLIC ACID",
        ],
    )
    def test_maps_safe_salicylic_acid_aliases(self, name: str) -> None:
        mapped = CommonIngredientAliasMapper().map_request(
            IngredientResolveRequest(name=name)
        )
        assert mapped.name == "살리실릭애씨드"

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("알로에신", "알로에신"),
            ("ALOESIN", "알로에신"),
            ("Hexapeptide-2", "헥사펩타이드-2"),
            ("hexapeptide 2", "헥사펩타이드-2"),
            ("서양 고추냉이 뿌리 추출물", "호스래디시뿌리추출물"),
            ("COCHLEARIA ARMORACIA ROOT EXTRACT", "호스래디시뿌리추출물"),
        ],
    )
    def test_maps_confirmed_case_ingredient_aliases(
        self,
        name: str,
        expected: str,
    ) -> None:
        mapped = CommonIngredientAliasMapper().map_request(
            IngredientResolveRequest(name=name)
        )

        assert mapped.name == expected

    @pytest.mark.parametrize("name", ["BHA", "티트리 오일", "티트리오일", "TEA TREE OIL"])
    def test_preserves_ambiguous_families_without_single_id_mapping(self, name: str) -> None:
        mapper = CommonIngredientAliasMapper()
        request = IngredientResolveRequest(name=name)

        assert mapper.map_request(request) == request
        assert mapper.is_ambiguous_family(request)
        assert len(mapper.family_candidates(request)) >= 2

    def test_custom_entries_and_empty_catalog(self) -> None:
        request = IngredientResolveRequest(name="테스트 별칭")
        mapper = CommonIngredientAliasMapper(
            [
                IngredientAliasEntry(
                    consumer_term="테스트별칭", standard_name_ko="테스트명", description="합성"
                )
            ]
        )
        assert mapper.map_request(request).name == "테스트명"
        request = IngredientResolveRequest(name="비타민C")
        assert CommonIngredientAliasMapper([]).map_request(request) == request

    def test_rejects_conflicting_normalized_aliases(self) -> None:
        with pytest.raises(ValueError, match="서로 다른 해석"):
            CommonIngredientAliasMapper(
                [
                    IngredientAliasEntry(
                        consumer_term="별 칭", standard_name_ko="A", description="합성"
                    ),
                    IngredientAliasEntry(
                        consumer_term="별칭", standard_name_ko="B", description="합성"
                    ),
                ]
            )

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("나이아신아마이드 사용 시 주의사항 알려줘", ["나이아신아마이드"]),
            ("BHA가 피지에 좋아?", ["BHA"]),
            ("비타민 C와 판테놀을 같이 써도 돼?", ["아스코빅애씨드", "판테놀"]),
        ],
    )
    def test_detects_known_mentions_in_current_user_message(
        self, message: str, expected: list[str]
    ) -> None:
        result = CommonIngredientAliasMapper().detect_mentions(
            IngredientMentionDetectionRequest(text=message)
        )
        assert result.mentions == expected

    @pytest.mark.parametrize(
        "message", ["비타민C 유도체 추천해줘", "vitamin c derivative가 궁금해"]
    )
    def test_does_not_reduce_derivative_request_to_pure_vitamin_c(self, message: str) -> None:
        result = CommonIngredientAliasMapper().detect_mentions(
            IngredientMentionDetectionRequest(text=message)
        )
        assert result.mentions == []


class TestEntityResolutionFallback:
    async def test_recovers_explicit_ingredient_when_llm_omits_mentions(self) -> None:
        scenario = FallbackScenario()
        scenario.llm.parsed = ParsedRequest(
            intents=[Intent.EVIDENCE_QA],
            query="나이아신아마이드 사용 시 주의사항 알려줘",
            ingredient_mentions=[],
        )
        app = scenario.create()

        await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )

        assert [request.name for request in scenario.ingredients.requests] == [
            "나이아신아마이드"
        ]
        assert scenario.search.requests[0].target_ids == ["test:niacinamide"]

    async def test_alias_retry_uses_repository_ids_without_rewriting_question(self) -> None:
        scenario = FallbackScenario()
        scenario.ingredients.register("아스코빅애씨드", "test:ascorbic")
        app = scenario.create()
        await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert [request.name for request in scenario.ingredients.requests] == [
            "나이아신아마이드",
            "비타민C",
            "아스코빅애씨드",
        ]
        assert scenario.search.requests[0].target_ids == ["test:niacinamide", "test:ascorbic"]
        assert scenario.search.requests[0].query == scenario.llm.parsed.query

    async def test_original_resolution_takes_precedence(self) -> None:
        scenario = FallbackScenario()
        scenario.ingredients.register("비타민C", "test:original")
        app = scenario.create()
        await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert len(scenario.ingredients.requests) == 2
        assert "test:original" in scenario.search.requests[0].target_ids

    async def test_alias_substring_hit_is_not_a_confirmed_derivative(self) -> None:
        scenario = FallbackScenario()
        scenario.ingredients.results["아스코빅애씨드"] = IngredientResolveResult(
            status=LookupStatus.SUCCESS,
            ingredient=IngredientRecord(
                ingredient_id="test:derivative", canonical_name="합성 유도체"
            ),
        )
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.PARTIAL
        assert scenario.search.requests[0].target_ids == []

    async def test_partial_resolution_searches_entire_question_once(self) -> None:
        scenario = FallbackScenario()
        scenario.evidence()
        scenario.llm.parsed.known_conditions = EvidenceConditions(route="topical")
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.PARTIAL
        assert output.follow_up_question is None
        assert output.citations
        assert len(scenario.search.requests) == 1
        request = scenario.search.requests[0]
        assert request.query == scenario.llm.parsed.query
        assert request.target_ids == request.combination_target_ids == []
        assert request.known_conditions.route == "topical"
        assert any("비타민C" in item.detail for item in output.unresolved)

    async def test_all_unknown_still_searches_and_reports_no_evidence(self) -> None:
        scenario = FallbackScenario()
        scenario.ingredients.results.clear()
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.PARTIAL
        assert not output.follow_up_question
        assert len(scenario.search.requests) == 1
        assert not scenario.search.requests[0].target_ids
        assert any(item.kind is UnresolvedKind.NO_EVIDENCE for item in output.unresolved)

    async def test_ambiguous_candidates_are_not_promoted_or_retried_as_aliases(self) -> None:
        scenario = FallbackScenario()
        scenario.ingredients.results["비타민C"] = IngredientResolveResult(
            status=LookupStatus.SUCCESS,
            ambiguous_candidates=[
                IngredientRecord(ingredient_id="test:a", canonical_name="합성 후보 A"),
                IngredientRecord(ingredient_id="test:b", canonical_name="합성 후보 B"),
            ],
        )
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.PARTIAL
        assert len(scenario.ingredients.requests) == 2
        assert scenario.search.requests[0].target_ids == []

    @pytest.mark.parametrize(
        "intent", [Intent.PRODUCT_DISCOVERY, Intent.ROUTINE_PLANNING, Intent.ROUTINE_SAVE]
    )
    async def test_mixed_intents_keep_strict_gate(self, intent: Intent) -> None:
        scenario = FallbackScenario()
        scenario.llm.parsed.intents.append(intent)
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.NEEDS_INPUT
        assert not scenario.search.requests
        assert not output.artifacts
        assert output.save_handoff is None

    @pytest.mark.parametrize("status", [LookupStatus.ERROR, LookupStatus.UNSUPPORTED])
    async def test_lookup_failure_is_not_a_free_text_fallback(self, status: LookupStatus) -> None:
        scenario = FallbackScenario()
        scenario.ingredients.results["비타민C"] = IngredientResolveResult(
            status=status, error_message="조회 장애"
        )
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.error_code is ErrorCode.TOOL_FAILED
        assert not scenario.search.requests
        assert len(scenario.ingredients.requests) == 2
        assert any(item.kind is UnresolvedKind.TOOL_FAILURE for item in output.unresolved)

    async def test_alias_retry_respects_tool_budget(self) -> None:
        scenario = FallbackScenario()
        scenario.llm.parsed.ingredient_mentions = ["비타민C"]
        app = scenario.create(ExecutionLimits(max_tool_calls=1))
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.error_code is ErrorCode.EXECUTION_LIMIT_REACHED
        assert len(scenario.ingredients.requests) == 1
        assert not scenario.search.requests

    async def test_lookup_failure_does_not_open_mixed_intent_gate(self) -> None:
        scenario = FallbackScenario()
        scenario.llm.parsed.intents.append(Intent.ROUTINE_PLANNING)
        scenario.ingredients.results["나이아신아마이드"] = IngredientResolveResult(
            status=LookupStatus.ERROR, error_message="조회 장애"
        )
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.NEEDS_INPUT
        assert output.error_code is ErrorCode.TOOL_FAILED
        assert not output.artifacts
        assert not scenario.search.requests

    async def test_missing_name_with_lookup_error_does_not_ask_user_to_fix_db(self) -> None:
        scenario = FallbackScenario()
        scenario.ingredients.results["나이아신아마이드"] = IngredientResolveResult(
            status=LookupStatus.ERROR, error_message="조회 장애"
        )
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.PARTIAL
        assert output.error_code is ErrorCode.TOOL_FAILED
        assert not output.follow_up_question
        assert not scenario.search.requests

    async def test_fallback_does_not_restore_only_the_known_subset_next_turn(self) -> None:
        scenario = FallbackScenario()
        app = scenario.create()
        factory = AgentTestFactory()
        await app.service.handle_turn(factory.request("room-a", "1", scenario.llm.parsed.query))
        scenario.llm.parsed = ParsedRequest(
            intents=[Intent.EVIDENCE_QA], query="그 성분의 주의사항은?"
        )
        output = await app.service.handle_turn(
            factory.request("room-a", "2", scenario.llm.parsed.query)
        )
        assert output.status is ChatStatus.NEEDS_INPUT
        assert len(scenario.search.requests) == 1

    async def test_document_status_does_not_block_fallback_evidence(self) -> None:
        scenario = FallbackScenario()
        scenario.evidence(EvidenceReviewStatus.UNREVIEWED)
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert scenario.claims.requests
        assert output.citations
        assert output.status is ChatStatus.PARTIAL

    async def test_unknown_pair_does_not_generate_combination_claims(self) -> None:
        scenario = FallbackScenario()
        scenario.evidence()
        scenario.llm.parsed.query = "나이아신아마이드와 비타민C를 같이 써도 괜찮아?"
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert len(scenario.search.requests) == 1
        assert scenario.search.requests[0].combination_target_ids == []
        assert not scenario.claims.requests
        assert not output.citations
        assert output.status is ChatStatus.PARTIAL

    @pytest.mark.parametrize("status", [LookupStatus.ERROR, LookupStatus.UNSUPPORTED])
    async def test_search_failures_remain_visible(self, status: LookupStatus) -> None:
        scenario = FallbackScenario()
        scenario.search.result = EvidenceSearchResult(
            status=status, error_message="검색 실패 테스트"
        )
        app = scenario.create()
        output = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", scenario.llm.parsed.query)
        )
        assert any("검색 실패 테스트" in item.detail for item in output.unresolved)
        assert output.status is ChatStatus.PARTIAL
        assert not output.citations
