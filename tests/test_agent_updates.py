"""데이터 계약·멀티턴·실패 복구에서 실제 오동작을 재현하는 회귀 검사."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from agent.adapters import FakeLlmClient, InMemoryChatHistoryRepository
from agent.context import ContextBuilder, ConversationSummarizer
from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.ports import IngredientRepository, TurnStorageError
from agent.rag.loaders.data_records import (
    DataRecordMapper,
    DataSourceContext,
    EvidenceData,
    EvidenceDataRequest,
    IngredientMasterData,
    KnowledgeFactData,
    KnowledgeFactRequest,
)
from agent.rag.pipeline import EvidenceApplicabilityEvaluator, EvidencePipeline
from agent.rag.ports import EvidenceRetriever
from agent.rag.schemas import (
    ApplicabilityRequest,
    ApplicabilityStatus,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    EvidenceSourceType,
    EvidenceTextKind,
    IngredientRecord,
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    ProductCandidateSet,
    RegulatoryConfidence,
    RoutinePlan,
    Weekday,
)
from agent.schemas import (
    AgentState,
    ChatMessage,
    ChatStatus,
    ContextLimits,
    ErrorCode,
    ExecutionLimits,
    Intent,
    MessagePageRequest,
    MessageRole,
    ParsedRequest,
    RegisterRoomRequest,
    RoomLookupRequest,
    SessionContextRequest,
    SessionContextResult,
    UnderstandingRequest,
)
from tests.test_agent_chat import AgentTestFactory


class SlowOnceLlm(FakeLlmClient):
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()

    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            await asyncio.Event().wait()
        return await super().understand(request)


class ContextFailureHistory(InMemoryChatHistoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    async def get_session_context(self, request: SessionContextRequest) -> SessionContextResult:
        if self.fail_once:
            self.fail_once = False
            raise TurnStorageError("문맥 복구 실패 테스트")
        return await super().get_session_context(request)


class AmbiguousIngredients(IngredientRepository):
    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        return IngredientResolveResult(
            status=LookupStatus.SUCCESS,
            ambiguous_candidates=[
                IngredientRecord(ingredient_id="a", canonical_name="후보 A"),
                IngredientRecord(ingredient_id="b", canonical_name="후보 B"),
            ],
        )


class SingleEvidenceRetriever(EvidenceRetriever):
    def __init__(self, record: EvidenceRecord) -> None:
        self.record = record

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        return EvidenceSearchResult(status=LookupStatus.SUCCESS, records=[self.record])


class UpdatedTestFactory(AgentTestFactory):
    def register(self, application: DevelopmentAgentApplication) -> None:
        application.history.register_room(
            RegisterRoomRequest(actor_id="user-a", chat_room_id="room-a", thread_id="thread-a")
        )

    async def snapshot(self, application: DevelopmentAgentApplication) -> SessionContextResult:
        room = await application.history.get_authorized_room(
            RoomLookupRequest(actor_id="user-a", chat_room_id="room-a")
        )
        return await application.history.get_session_context(SessionContextRequest(room=room))


class TestUpdatedChat:
    async def test_pending_question_preserves_weekdays_and_new_topic_can_replace_it(self) -> None:
        factory = UpdatedTestFactory()
        app = factory.create()
        question = await app.service.handle_turn(
            factory.request("room-a", "1", "월요일 제외하고 루틴 짜줘")
        )
        assert question.status is ChatStatus.NEEDS_INPUT
        result = await app.service.handle_turn(
            factory.request("room-a", "2", "데모 판테놀 젤 크림이야")
        )
        plan = next(item for item in result.artifacts if isinstance(item, RoutinePlan))
        assert all(item.weekday is not Weekday.MONDAY for item in plan.placements)
        await app.service.handle_turn(factory.request("room-b", "3", "루틴 짜줘"))
        changed = await app.service.handle_turn(
            factory.request("room-b", "4", "나이아신아마이드 효능 알려줘")
        )
        assert changed.intents == [Intent.EVIDENCE_QA]
        assert changed.citations

    async def test_rejected_product_and_category_survive_multiple_modifications(self) -> None:
        factory = UpdatedTestFactory()
        app = factory.create()
        await app.service.handle_turn(factory.request("room-a", "1", "보습 크림 추천해줘"))
        await app.service.handle_turn(
            factory.request("room-a", "2", "1번은 싫어. 더 가벼운 걸로 바꿔줘")
        )
        result = await app.service.handle_turn(factory.request("room-a", "3", "다시 바꿔줘"))
        candidates = next(
            item for item in result.artifacts if isinstance(item, ProductCandidateSet)
        )
        assert [item.product.product_id for item in candidates.candidates] == [
            "product:panthenol-gel"
        ]
        context = await factory.snapshot(app)
        assert context.snapshot is not None
        assert "product:ceramide-cream" in context.snapshot.task_context.rejected_product_ids

    async def test_control_routes_and_save_handoff_do_not_fabricate_persistence(self) -> None:
        factory = UpdatedTestFactory()
        app = factory.create()
        for request_id, message, expected in (
            ("1", "안녕하세요", Intent.GENERAL_CHAT),
            ("2", "오늘 날씨 어때", Intent.OUT_OF_SCOPE),
            ("3", "뭔가 해줘", Intent.CLARIFICATION),
        ):
            result = await app.service.handle_turn(factory.request("room-a", request_id, message))
            assert result.intents == [expected]
            assert not result.artifacts and not result.citations
        plan_output = await app.service.handle_turn(
            factory.request("room-a", "4", "데모 판테놀 젤 크림 루틴 짜줘")
        )
        plan = next(item for item in plan_output.artifacts if isinstance(item, RoutinePlan))
        saved = await app.service.handle_turn(factory.request("room-a", "5", "저장해줘"))
        assert saved.save_handoff is not None
        assert saved.save_handoff.routine_id == plan.routine_id
        assert saved.save_handoff.version == plan.version
        assert "저장 완료" not in saved.message
        skipped = await app.service.handle_turn(factory.request("room-a", "6", "저장하지 마"))
        assert skipped.save_handoff is None

    async def test_ambiguous_match_is_not_promoted_to_two_confirmed_ingredients(self) -> None:
        factory = UpdatedTestFactory()
        app = DevelopmentAgentFactory(ingredient_repository=AmbiguousIngredients()).create()
        factory.register(app)
        result = await app.service.handle_turn(factory.request("room-a", "1", "성분 효능 알려줘"))
        assert result.status is ChatStatus.NEEDS_INPUT
        assert not result.citations

    async def test_candidate_evidence_uses_referenced_products(self) -> None:
        factory = UpdatedTestFactory()
        app = factory.create()
        await app.service.handle_turn(factory.request("room-a", "1", "보습 크림 추천해줘"))
        result = await app.service.handle_turn(
            factory.request("room-a", "2", "2번 성분 근거 알려줘")
        )
        assert result.intents == [Intent.EVIDENCE_QA]
        assert {item.evidence_id for item in result.citations} == {
            "demo-evidence:panthenol",
            "demo-evidence:glycerin",
        }

    async def test_window_is_bounded_but_history_and_candidates_survive_rebuild(self) -> None:
        factory = UpdatedTestFactory()
        limits = ContextLimits(recent_message_limit=4, summary_trigger=8, summary_char_limit=180)
        app = DevelopmentAgentFactory(context_limits=limits).create()
        factory.register(app)
        await app.service.handle_turn(factory.request("room-a", "1", "보습 크림 추천해줘"))
        for number in range(2, 13):
            await app.service.handle_turn(factory.request("room-a", str(number), "안녕하세요"))
        context = await factory.snapshot(app)
        assert context.snapshot is not None and context.snapshot.summary is not None
        assert len(context.snapshot.messages) <= limits.recent_message_limit
        assert len(context.snapshot.summary.content) <= limits.summary_char_limit
        room = await app.history.get_authorized_room(
            RoomLookupRequest(actor_id="user-a", chat_room_id="room-a")
        )
        history = await app.history.get_messages(MessagePageRequest(room=room, limit=100))
        assert len(history.messages) == 24
        assert [item.sequence for item in history.messages] == list(range(1, 25))
        rebuilt = DevelopmentAgentFactory(history=app.history, context_limits=limits).create()
        result = await rebuilt.service.handle_turn(
            factory.request("room-a", "13", "2번으로 루틴 짜줘")
        )
        plan = next(item for item in result.artifacts if isinstance(item, RoutinePlan))
        assert {item.product_id for item in plan.placements} == {"product:panthenol-gel"}

    async def test_timeout_unlocks_room_and_failed_checkpoint_is_not_canonical(self) -> None:
        factory = UpdatedTestFactory()
        app = DevelopmentAgentFactory(
            llm=SlowOnceLlm(),
            execution_limits=ExecutionLimits(timeout_seconds=0.2),
        ).create()
        factory.register(app)
        failed = await app.service.handle_turn(factory.request("room-a", "1", "보습 크림 추천해줘"))
        assert failed.error_code is ErrorCode.EXECUTION_LIMIT_REACHED
        result = await app.service.handle_turn(factory.request("room-a", "2", "안녕하세요"))
        assert result.status is ChatStatus.COMPLETED
        context = await factory.snapshot(app)
        assert context.snapshot is not None
        assert all(item.request_id != "1" for item in context.snapshot.messages)
        assert [item.sequence for item in context.snapshot.messages] == [2, 3]

    async def test_context_restore_failure_unlocks_room(self) -> None:
        factory = UpdatedTestFactory()
        app = DevelopmentAgentFactory(history=ContextFailureHistory()).create()
        factory.register(app)
        failed = await app.service.handle_turn(factory.request("room-a", "1", "안녕하세요"))
        assert failed.status is ChatStatus.ERROR
        result = await app.service.handle_turn(factory.request("room-a", "2", "안녕하세요"))
        assert result.status is ChatStatus.COMPLETED

    async def test_cancelled_graph_releases_room(self) -> None:
        factory = UpdatedTestFactory()
        llm = SlowOnceLlm()
        app = DevelopmentAgentFactory(llm=llm).create()
        factory.register(app)
        task = asyncio.create_task(
            app.service.handle_turn(factory.request("room-a", "1", "보습 크림 추천해줘"))
        )
        await asyncio.wait_for(llm.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = await app.service.handle_turn(factory.request("room-a", "2", "안녕하세요"))
        assert result.status is ChatStatus.COMPLETED

    async def test_failed_routine_revision_cannot_request_saving_old_version(self) -> None:
        factory = UpdatedTestFactory()
        app = factory.create()
        await app.service.handle_turn(
            factory.request("room-a", "1", "데모 판테놀 젤 크림 루틴 짜줘")
        )
        result = await app.service.handle_turn(
            factory.request(
                "room-a",
                "2",
                "월요일 화요일 수요일 목요일 금요일 주말 제외하고 저장해줘",
            )
        )
        assert result.status is ChatStatus.PARTIAL
        assert result.save_handoff is None

    def test_thread_id_cannot_be_shared_by_different_rooms(self) -> None:
        factory = UpdatedTestFactory()
        app = factory.create()
        with pytest.raises(TurnStorageError, match="thread_id"):
            app.history.register_room(
                RegisterRoomRequest(
                    actor_id="user-a",
                    chat_room_id="room-c",
                    thread_id="thread-a",
                )
            )

    async def test_rejected_candidate_is_removed_from_existing_routine(self) -> None:
        factory = UpdatedTestFactory()
        app = factory.create()
        await app.service.handle_turn(factory.request("room-a", "1", "보습 크림 추천해줘"))
        await app.service.handle_turn(
            factory.request(
                "room-a",
                "2",
                "데모 세라마이드 크림과 데모 판테놀 젤 크림 루틴 짜줘",
            )
        )
        result = await app.service.handle_turn(
            factory.request("room-a", "3", "1번 제외하고 루틴 바꿔줘")
        )
        plan = next(item for item in result.artifacts if isinstance(item, RoutinePlan))
        assert {item.product_id for item in plan.placements} == {"product:panthenol-gel"}


class TestContextWindow:
    def test_pre_trigger_messages_are_covered_and_long_messages_are_trimmed_for_llm(self) -> None:
        state = AgentState(
            context_limits=ContextLimits(
                recent_message_limit=3,
                summary_trigger=10,
                message_char_limit=20,
            )
        )
        state.messages = [
            ChatMessage(
                message_id=str(number),
                request_id=str(number),
                role=MessageRole.USER,
                content="긴 대화 내용 " * 30,
                sequence=number,
            )
            for number in range(1, 6)
        ]
        context = ContextBuilder(ConversationSummarizer()).build(state)
        assert context.summary is not None and context.summary.covered_through_sequence == 2
        assert [item.sequence for item in context.recent_messages] == [3, 4, 5]
        assert all(len(item.content) <= 20 for item in context.recent_messages)
        assert all(len(item.content) > 20 for item in state.messages)


class TestDataEvidence:
    def record(self) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id="record",
            source_id="source",
            source_title="테스트 자료",
            document_version="test-version",
            text="테스트 주장",
            locator="row:1",
            conditions=EvidenceConditions(route="oral"),
            review_status=EvidenceReviewStatus.VERIFIED,
            is_demo=False,
        )

    async def test_pipeline_passes_conditions_and_rejects_known_route_mismatch(self) -> None:
        pipeline = EvidencePipeline(
            SingleEvidenceRetriever(self.record()), EvidenceApplicabilityEvaluator()
        )
        result = await pipeline.run(
            EvidenceSearchRequest(
                query="근거",
                known_conditions=EvidenceConditions(route="topical"),
            )
        )
        assert result.assessments[0].status is ApplicabilityStatus.NOT_APPLICABLE

    def test_unknown_review_and_free_text_conditions_do_not_become_applicable(self) -> None:
        evaluator = EvidenceApplicabilityEvaluator()
        record = self.record()
        record.review_status = EvidenceReviewStatus.UNREVIEWED
        unknown = evaluator.assess(
            ApplicabilityRequest(evidence=record, known_conditions=record.conditions)
        )
        assert unknown.status is ApplicabilityStatus.UNKNOWN
        record.review_status = EvidenceReviewStatus.VERIFIED
        record.conditions = EvidenceConditions(concentration="0.5~7.0%")
        limited = evaluator.assess(
            ApplicabilityRequest(
                evidence=record, known_conditions=EvidenceConditions(concentration="2%")
            )
        )
        assert limited.status is ApplicabilityStatus.LIMITED

    def test_mfds_preserves_jurisdiction_conditions_and_does_not_invent_source_version(
        self,
    ) -> None:
        record = DataRecordMapper().mfds(
            EvidenceDataRequest(
                data=EvidenceData(
                    id=UUID(int=1),
                    ingredient_id=UUID(int=2),
                    claim="테스트 국가의 제한 요약",
                    conditions="씻어내는 제품에 한함",
                    jurisdiction="EU",
                    source_title="테스트 MFDS 응답",
                    source_url="https://example.test/source",
                    collected_at=datetime(2026, 9, 10, tzinfo=UTC),
                ),
                source=DataSourceContext(
                    source_id="notice", source_title="자료", locator="api-row:1"
                ),
            )
        )
        assert record.jurisdiction == "EU"
        assert record.raw_conditions == "씻어내는 제품에 한함"
        assert record.source_type is EvidenceSourceType.MFDS
        assert record.text_kind is EvidenceTextKind.SUMMARY
        assert record.review_status is EvidenceReviewStatus.UNREVIEWED
        assert record.document_version is None and record.published_at is None
        assert not record.is_demo

    def test_master_uses_internal_uuid_and_knowledge_regulation_review_is_not_global(self) -> None:
        mapper = DataRecordMapper()
        ingredient = mapper.ingredient(
            IngredientMasterData(
                id=UUID(int=2),
                ingredient_code=123,
                standard_name_ko="테스트 성분",
                old_names_ko=["이전 명칭"],
                source_version="사전 v1",
            )
        )
        assert ingredient.ingredient_id == str(UUID(int=2))
        assert ingredient.ingredient_code == 123 and ingredient.aliases == ["이전 명칭"]
        record = mapper.knowledge(
            KnowledgeFactRequest(
                data=KnowledgeFactData(
                    id=UUID(int=3),
                    ingredient_id=UUID(int=2),
                    source_row_no=42,
                    inci_name="Example",
                    compounding_regulation_text="혼합 출처 규제 요약",
                    regulatory_confidence=RegulatoryConfidence.VERIFIED,
                ),
                source=DataSourceContext(
                    source_id="knowledge", source_title="지식성분", locator="Sheet1"
                ),
            )
        )
        assert record.regulatory_confidence is RegulatoryConfidence.VERIFIED
        assert record.review_status is EvidenceReviewStatus.UNREVIEWED
        assert "row=42" in record.locator
