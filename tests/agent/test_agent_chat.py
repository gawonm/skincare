"""LangGraph LLM·RAG 프레임의 핵심 채팅 계약 검증."""

from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.rag.schemas import ProductCandidateSet, RoutinePlan, Weekday
from agent.schemas import (
    ArtifactLookupRequest,
    AuthenticatedChatContext,
    BeginTurnRequest,
    ChatServiceRequest,
    ChatStatus,
    ChatTurnInput,
    ConversationSummary,
    ErrorCode,
    ExecutionLimits,
    Intent,
    MessagePageRequest,
    RegisterRoomRequest,
    RoomLookupRequest,
    SaveSummaryRequest,
    SessionContextRequest,
    SummarySaveStatus,
    TurnBeginStatus,
    UnresolvedKind,
)
from agent.service import RequestIdentityFactory


class AgentTestFactory:
    """각 테스트가 체크포인트와 히스토리를 공유하지 않게 격리한다."""

    def create(
        self,
        execution_limits: ExecutionLimits | None = None,
    ) -> DevelopmentAgentApplication:
        application = DevelopmentAgentFactory(execution_limits=execution_limits).create()
        application.history.register_room(
            RegisterRoomRequest(actor_id="user-a", chat_room_id="room-a", thread_id="thread-a")
        )
        application.history.register_room(
            RegisterRoomRequest(actor_id="user-a", chat_room_id="room-b", thread_id="thread-b")
        )
        return application

    def request(
        self,
        room_id: str,
        request_id: str,
        message: str,
        actor_id: str = "user-a",
    ) -> ChatServiceRequest:
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(actor_id=actor_id, chat_room_id=room_id),
            turn=ChatTurnInput(
                chat_room_id=room_id,
                request_id=request_id,
                message=message,
            ),
        )


class TestAgentChatService:
    async def test_three_intents_and_composite_request(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()

        product = await application.service.handle_turn(
            factory.request("room-a", "product-1", "가벼운 보습 크림 추천해줘")
        )
        evidence = await application.service.handle_turn(
            factory.request("room-b", "evidence-1", "나이아신아마이드 역할과 근거를 알려줘")
        )
        composite = await application.service.handle_turn(
            factory.request(
                "room-a",
                "composite-1",
                "데모 판테놀 젤 크림을 추천하고 일정도 짜줘",
            )
        )

        assert product.status is ChatStatus.COMPLETED
        assert product.intents == [Intent.PRODUCT_DISCOVERY]
        assert any(isinstance(artifact, ProductCandidateSet) for artifact in product.artifacts)
        assert evidence.status is ChatStatus.COMPLETED
        assert evidence.intents == [Intent.EVIDENCE_QA]
        assert evidence.citations
        assert composite.intents == [Intent.PRODUCT_DISCOVERY, Intent.ROUTINE_PLANNING]
        assert any(isinstance(artifact, RoutinePlan) for artifact in composite.artifacts)

    async def test_question_then_continue_in_same_room(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()

        question = await application.service.handle_turn(
            factory.request("room-a", "question-1", "이 제품들 어떻게 써?")
        )
        continuation = await application.service.handle_turn(
            factory.request(
                "room-a",
                "question-2",
                "데모 세라마이드 크림과 데모 판테놀 젤 크림이야",
            )
        )

        assert question.status is ChatStatus.NEEDS_INPUT
        assert question.follow_up_question is not None
        assert continuation.status is ChatStatus.COMPLETED
        plans = [
            artifact for artifact in continuation.artifacts if isinstance(artifact, RoutinePlan)
        ]
        assert plans
        assert {placement.product_id for placement in plans[0].placements} == {
            "product:ceramide-cream",
            "product:panthenol-gel",
        }

    async def test_candidate_reference_and_schedule_change(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        await application.service.handle_turn(
            factory.request("room-a", "reference-1", "보습 크림 추천해줘")
        )
        plan_output = await application.service.handle_turn(
            factory.request("room-a", "reference-2", "2번으로 일정 짜줘")
        )
        changed_output = await application.service.handle_turn(
            factory.request("room-a", "reference-3", "월요일은 빼줘")
        )

        first_plan = next(
            artifact for artifact in plan_output.artifacts if isinstance(artifact, RoutinePlan)
        )
        changed_plan = next(
            artifact for artifact in changed_output.artifacts if isinstance(artifact, RoutinePlan)
        )
        assert {placement.product_id for placement in first_plan.placements} == {
            "product:panthenol-gel"
        }
        assert changed_plan.version == first_plan.version + 1
        assert all(placement.weekday is not Weekday.MONDAY for placement in changed_plan.placements)

    async def test_rejected_candidate_is_not_selected_again(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        await application.service.handle_turn(
            factory.request("room-a", "reject-1", "보습 크림 추천해줘")
        )
        replacement = await application.service.handle_turn(
            factory.request("room-a", "reject-2", "1번은 싫어. 더 가벼운 걸로 바꿔줘")
        )

        candidate_set = next(
            artifact
            for artifact in replacement.artifacts
            if isinstance(artifact, ProductCandidateSet)
        )
        assert {candidate.product.product_id for candidate in candidate_set.candidates} == {
            "product:panthenol-gel"
        }

    async def test_rooms_are_isolated_and_access_is_checked(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        await application.service.handle_turn(
            factory.request("room-a", "isolation-1", "보습 크림 추천해줘")
        )

        isolated = await application.service.handle_turn(
            factory.request("room-b", "isolation-2", "1번으로 일정 짜줘")
        )
        forbidden = await application.service.handle_turn(
            factory.request("room-a", "isolation-3", "근거 알려줘", actor_id="user-b")
        )

        assert isolated.status is ChatStatus.NEEDS_INPUT
        assert forbidden.status is ChatStatus.ERROR
        assert forbidden.error_code is ErrorCode.ROOM_FORBIDDEN

    async def test_duplicate_request_returns_one_saved_turn(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        request = factory.request("room-a", "duplicate-1", "가벼운 크림 추천해줘")

        first = await application.service.handle_turn(request)
        second = await application.service.handle_turn(request)
        room = await application.history.get_authorized_room(
            RoomLookupRequest(actor_id="user-a", chat_room_id="room-a")
        )
        messages = await application.history.get_messages(MessagePageRequest(room=room, limit=10))

        assert first == second
        assert len(messages.messages) == 2

    async def test_artifact_lookup_and_summary_revision_contract(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        output = await application.service.handle_turn(
            factory.request("room-a", "artifact-1", "보습 크림 추천해줘")
        )
        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )
        room = await application.history.get_authorized_room(
            RoomLookupRequest(actor_id="user-a", chat_room_id="room-a")
        )

        artifacts = await application.history.get_artifacts(
            ArtifactLookupRequest(
                room=room,
                candidate_set_id=candidate_set.candidate_set_id,
            )
        )
        saved = await application.history.save_summary(
            SaveSummaryRequest(
                room=room,
                summary=ConversationSummary(
                    content="테스트 요약",
                    version=1,
                    covered_through_sequence=1,
                ),
                expected_revision=1,
            )
        )
        stale = await application.history.save_summary(
            SaveSummaryRequest(
                room=room,
                summary=ConversationSummary(
                    content="늦게 끝난 오래된 요약",
                    version=1,
                    covered_through_sequence=1,
                ),
                expected_revision=1,
            )
        )

        assert artifacts.artifacts == [candidate_set]
        assert saved.status is SummarySaveStatus.SAVED
        assert stale.status is SummarySaveStatus.REVISION_CONFLICT

    async def test_same_request_id_with_different_body_conflicts(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        await application.service.handle_turn(
            factory.request("room-a", "conflict-1", "보습 크림 추천해줘")
        )
        conflict = await application.service.handle_turn(
            factory.request("room-a", "conflict-1", "나이아신아마이드 근거 알려줘")
        )

        assert conflict.status is ChatStatus.ERROR
        assert conflict.error_code is ErrorCode.REQUEST_CONFLICT

    async def test_in_progress_request_is_explicit(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        turn = factory.request("room-a", "progress-1", "보습 크림 추천해줘").turn
        room = await application.history.get_authorized_room(
            RoomLookupRequest(actor_id="user-a", chat_room_id="room-a")
        )
        identities = RequestIdentityFactory()
        begin_request = BeginTurnRequest(
            room=room,
            turn=turn,
            identifiers=identities.create_identifiers(turn),
            input_fingerprint=identities.create_fingerprint(turn),
        )

        first = await application.history.begin_turn(begin_request)
        second = await application.history.begin_turn(begin_request)
        other_turn = factory.request("room-a", "progress-2", "나이아신아마이드 근거 알려줘").turn
        different_request = await application.history.begin_turn(
            BeginTurnRequest(
                room=room,
                turn=other_turn,
                identifiers=identities.create_identifiers(other_turn),
                input_fingerprint=identities.create_fingerprint(other_turn),
            )
        )

        assert first.status is TurnBeginStatus.NEW
        assert second.status is TurnBeginStatus.IN_PROGRESS
        assert different_request.status is TurnBeginStatus.IN_PROGRESS

    async def test_response_save_retry_reuses_generated_result(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        request = factory.request("room-a", "save-1", "가벼운 보습 크림 추천해줘")
        application.history.fail_next_complete()

        failed = await application.service.handle_turn(request)
        retried = await application.service.handle_turn(request)

        assert failed.status is ChatStatus.ERROR
        assert failed.error_code is ErrorCode.RESPONSE_SAVE_FAILED
        assert retried.status is ChatStatus.COMPLETED
        assert retried.assistant_message_id == failed.assistant_message_id

    async def test_search_failure_and_no_evidence_are_distinct(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        application.evidence_retriever.fail_next_search()

        failure = await application.service.handle_turn(
            factory.request("room-a", "search-1", "나이아신아마이드 근거 알려줘")
        )
        no_result = await application.service.handle_turn(
            factory.request("room-a", "search-2", "아젤라익산 근거 알려줘")
        )

        assert failure.status is ChatStatus.PARTIAL
        assert failure.error_code is ErrorCode.TOOL_FAILED
        assert no_result.status is ChatStatus.PARTIAL
        assert no_result.error_code is None

    async def test_long_conversation_summary_keeps_structured_candidates(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        await application.service.handle_turn(
            factory.request("room-a", "summary-0", "보습 크림 추천해줘")
        )
        for index in range(1, 7):
            await application.service.handle_turn(
                factory.request(
                    "room-a",
                    f"summary-{index}",
                    "나이아신아마이드 근거 알려줘",
                )
            )
        room = await application.history.get_authorized_room(
            RoomLookupRequest(actor_id="user-a", chat_room_id="room-a")
        )
        context = await application.history.get_session_context(SessionContextRequest(room=room))

        assert context.snapshot is not None
        assert context.snapshot.summary is not None
        assert context.snapshot.candidate_set is not None

    async def test_committed_snapshot_recovers_with_new_checkpointer(self) -> None:
        factory = AgentTestFactory()
        first_application = factory.create()
        await first_application.service.handle_turn(
            factory.request("room-a", "recover-1", "보습 크림 추천해줘")
        )
        recovered_application = DevelopmentAgentFactory(history=first_application.history).create()

        recovered = await recovered_application.service.handle_turn(
            factory.request("room-a", "recover-2", "2번으로 일정 짜줘")
        )

        assert recovered.status is ChatStatus.COMPLETED
        plan = next(
            artifact for artifact in recovered.artifacts if isinstance(artifact, RoutinePlan)
        )
        assert {placement.product_id for placement in plan.placements} == {"product:panthenol-gel"}

    async def test_unpublished_values_remain_unresolved_without_repeated_question(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()

        output = await application.service.handle_turn(
            factory.request(
                "room-a",
                "unknown-1",
                "나이아신아마이드의 농도와 pH 근거를 알려줘",
            )
        )

        assert output.status is ChatStatus.COMPLETED
        assert output.follow_up_question is None
        assert any("농도 또는 pH" in item.detail for item in output.unresolved)

    async def test_reported_experience_is_kept_as_user_value(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()
        await application.service.handle_turn(
            factory.request("room-a", "experience-1", "레티놀을 바르니 따가웠어")
        )
        room = await application.history.get_authorized_room(
            RoomLookupRequest(actor_id="user-a", chat_room_id="room-a")
        )

        context = await application.history.get_session_context(SessionContextRequest(room=room))

        assert context.snapshot is not None
        assert [experience.value for experience in context.snapshot.profile.experiences] == [
            "레티놀을 바르니 따가웠어"
        ]

    async def test_price_condition_is_reported_as_unsupported(self) -> None:
        factory = AgentTestFactory()
        application = factory.create()

        output = await application.service.handle_turn(
            factory.request("room-a", "price-1", "2만원 이하 보습 크림 추천해줘")
        )

        assert output.status is ChatStatus.PARTIAL
        assert any(item.kind is UnresolvedKind.UNSUPPORTED_CONDITION for item in output.unresolved)

    async def test_execution_counter_resets_for_new_request(self) -> None:
        factory = AgentTestFactory()
        application = factory.create(
            execution_limits=ExecutionLimits(max_tool_calls=2, max_revisions=1)
        )
        limited = await application.service.handle_turn(
            factory.request(
                "room-a",
                "limit-1",
                "데모 판테놀 젤 크림을 추천하고 일정도 짜줘",
            )
        )
        next_turn = await application.service.handle_turn(
            factory.request("room-a", "limit-2", "나이아신아마이드 근거 알려줘")
        )

        assert limited.status is ChatStatus.PARTIAL
        assert limited.error_code is ErrorCode.EXECUTION_LIMIT_REACHED
        assert next_turn.status is ChatStatus.COMPLETED
