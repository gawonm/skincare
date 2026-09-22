"""`SqlAlchemyChatHistoryRepository`를 실제 로컬 DB로 검증한다.

대부분의 테스트는 `session` 픽스처의 바깥 트랜잭션 위에서 SAVEPOINT로 돌려, 어댑터가 commit해도
로컬 DB에 데이터가 남지 않는다. 동시 요청 테스트만 서로 다른 연결이 필요해서 실제로 commit하고
마지막에 계정을 지워(FK CASCADE) 정리한다.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.ports import RoomAccessDeniedError, RoomNotFoundError, TurnStorageError
from agent.rag.schemas import ProductCandidateSet, RoutinePlan
from agent.schemas import (
    ArtifactLookupRequest,
    AuthorizedRoom,
    BeginTurnRequest,
    BeginTurnResult,
    ChatMessage,
    ChatStatus,
    ChatTurnInput,
    ChatTurnOutput,
    CompleteTurnRequest,
    ConversationSummary,
    MarkTurnFailedRequest,
    MessagePageRequest,
    MessageRole,
    RoomLookupRequest,
    SaveSummaryRequest,
    SessionContextRequest,
    SessionSnapshot,
    StageTurnResultRequest,
    SummarySaveStatus,
    TurnBeginStatus,
    TurnFailureCode,
    TurnIdentifiers,
)
from backend.repositories.chat_room_repository import ChatRoomRepository
from backend.services.chat_history import SqlAlchemyChatHistoryRepository
from core.config import settings
from core.database import Database
from models.chat_room import ChatRoom
from models.user import AgeGroup, Gender, User


class ChatHistoryFixtures:
    """테스트가 공유하는 계정·방·요청 생성 도우미."""

    async def create_user(self, session: AsyncSession) -> User:
        user = User(
            email=f"chat-{uuid4()}@example.com",
            hashed_password="not-a-real-hash",
            name="채팅 테스트",
            gender=Gender.UNSPECIFIED,
            age_group=AgeGroup.TWENTIES,
            terms_agreed=True,
            terms_agreed_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()
        return user

    def room(self, chat_room: ChatRoom) -> AuthorizedRoom:
        return AuthorizedRoom(
            actor_id=str(chat_room.user_id),
            chat_room_id=str(chat_room.id),
            thread_id=str(chat_room.thread_id),
        )

    def begin_request(
        self,
        room: AuthorizedRoom,
        request_id: str,
        *,
        message: str = "레티놀 써도 돼?",
        fingerprint: str | None = None,
    ) -> BeginTurnRequest:
        return BeginTurnRequest(
            room=room,
            turn=ChatTurnInput(
                chat_room_id=room.chat_room_id, request_id=request_id, message=message
            ),
            identifiers=TurnIdentifiers(
                user_message_id=str(uuid4()), assistant_message_id=str(uuid4())
            ),
            input_fingerprint=fingerprint or f"fp-{request_id}",
        )

    def output(
        self,
        room: AuthorizedRoom,
        request: BeginTurnRequest,
        *,
        artifacts: list[ProductCandidateSet | RoutinePlan] | None = None,
    ) -> ChatTurnOutput:
        return ChatTurnOutput(
            chat_room_id=room.chat_room_id,
            request_id=request.turn.request_id,
            assistant_message_id=request.identifiers.assistant_message_id,
            status=ChatStatus.COMPLETED,
            message="같이 써도 되지만 시간대를 나눠 쓰세요.",
            artifacts=artifacts or [],
        )

    def snapshot(
        self,
        request: BeginTurnRequest,
        user_message: ChatMessage,
        output: ChatTurnOutput,
        *,
        summary: ConversationSummary | None = None,
    ) -> SessionSnapshot:
        assistant_message = ChatMessage(
            message_id=output.assistant_message_id,
            request_id=request.turn.request_id,
            role=MessageRole.ASSISTANT,
            content=output.message,
            sequence=user_message.sequence + 1,
        )
        return SessionSnapshot(
            messages=[user_message, assistant_message],
            summary=summary,
            last_completed_request_id=request.turn.request_id,
        )


@pytest_asyncio.fixture
async def chat_room(session: AsyncSession) -> ChatRoom:
    user = await ChatHistoryFixtures().create_user(session)
    return await ChatRoomRepository(session).get_or_create_for_user(user.id)


@pytest.fixture
def history(session: AsyncSession) -> SqlAlchemyChatHistoryRepository:
    # 어댑터가 자기 세션을 열어 commit해도 테스트의 바깥 트랜잭션 안에서 SAVEPOINT로만 처리된다
    factory = async_sessionmaker(
        bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    return SqlAlchemyChatHistoryRepository(factory)


class TestChatRoomProvisioning:
    async def test_get_or_create_returns_same_room_for_same_user(
        self, session: AsyncSession
    ) -> None:
        user = await ChatHistoryFixtures().create_user(session)
        repository = ChatRoomRepository(session)

        first = await repository.get_or_create_for_user(user.id)
        second = await repository.get_or_create_for_user(user.id)

        assert first.id == second.id


class TestRoomAuthorization:
    async def test_owner_gets_room_with_thread_id(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = await history.get_authorized_room(
            RoomLookupRequest(actor_id=str(chat_room.user_id), chat_room_id=str(chat_room.id))
        )

        assert room.thread_id == str(chat_room.thread_id)

    async def test_other_actor_is_denied(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        with pytest.raises(RoomAccessDeniedError):
            await history.get_authorized_room(
                RoomLookupRequest(actor_id=str(uuid4()), chat_room_id=str(chat_room.id))
            )

    @pytest.mark.parametrize("room_id", [str(uuid4()), "not-a-uuid"])
    async def test_unknown_or_malformed_room_is_not_found(
        self, history: SqlAlchemyChatHistoryRepository, room_id: str
    ) -> None:
        with pytest.raises(RoomNotFoundError):
            await history.get_authorized_room(
                RoomLookupRequest(actor_id=str(uuid4()), chat_room_id=room_id)
            )


class TestTurnLifecycle:
    fixtures = ChatHistoryFixtures()

    async def _begin(
        self, history: SqlAlchemyChatHistoryRepository, request: BeginTurnRequest
    ) -> BeginTurnResult:
        return await history.begin_turn(request)

    async def _complete(
        self,
        history: SqlAlchemyChatHistoryRepository,
        room: AuthorizedRoom,
        request: BeginTurnRequest,
        user_message: ChatMessage,
        *,
        artifacts: list[ProductCandidateSet | RoutinePlan] | None = None,
        summary: ConversationSummary | None = None,
    ) -> ChatTurnOutput:
        output = self.fixtures.output(room, request, artifacts=artifacts)
        snapshot = self.fixtures.snapshot(request, user_message, output, summary=summary)
        await history.stage_turn_result(
            StageTurnResultRequest(
                room=room, request_id=request.turn.request_id, output=output, snapshot=snapshot
            )
        )
        await history.complete_turn(
            CompleteTurnRequest(
                room=room, request_id=request.turn.request_id, output=output, snapshot=snapshot
            )
        )
        return output

    async def test_new_turn_stores_user_message_with_agent_issued_id(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        request = self.fixtures.begin_request(room, "r1")

        result = await self._begin(history, request)

        assert result.status is TurnBeginStatus.NEW
        assert result.user_message is not None
        assert result.user_message.message_id == request.identifiers.user_message_id
        assert result.user_message.sequence == 1

    async def test_same_request_while_in_progress_reports_in_progress(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        request = self.fixtures.begin_request(room, "r1")
        await self._begin(history, request)

        result = await self._begin(history, request)

        assert result.status is TurnBeginStatus.IN_PROGRESS

    async def test_same_request_with_different_input_is_conflict(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        await self._begin(history, self.fixtures.begin_request(room, "r1", fingerprint="a"))

        result = await self._begin(
            history, self.fixtures.begin_request(room, "r1", fingerprint="b")
        )

        assert result.status is TurnBeginStatus.CONFLICT

    async def test_other_request_is_rejected_while_room_has_active_turn(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        await self._begin(history, self.fixtures.begin_request(room, "r1"))

        result = await self._begin(history, self.fixtures.begin_request(room, "r2"))

        assert result.status is TurnBeginStatus.IN_PROGRESS

    async def test_completed_turn_replays_stored_output_and_saves_assistant_message(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        request = self.fixtures.begin_request(room, "r1")
        begun = await self._begin(history, request)
        assert begun.user_message is not None
        output = await self._complete(history, room, request, begun.user_message)

        replay = await self._begin(history, request)
        page = await history.get_messages(MessagePageRequest(room=room))

        assert replay.status is TurnBeginStatus.COMPLETED
        assert replay.output == output
        assert [message.role for message in page.messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]
        assert page.messages[1].message_id == output.assistant_message_id

    async def test_staged_turn_is_returned_so_caller_can_finish_saving(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        request = self.fixtures.begin_request(room, "r1")
        begun = await self._begin(history, request)
        assert begun.user_message is not None
        output = self.fixtures.output(room, request)
        snapshot = self.fixtures.snapshot(request, begun.user_message, output)
        await history.stage_turn_result(
            StageTurnResultRequest(room=room, request_id="r1", output=output, snapshot=snapshot)
        )

        replay = await self._begin(history, request)

        assert replay.status is TurnBeginStatus.STAGED
        assert replay.output == output

    async def test_complete_rejects_output_different_from_staged(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        request = self.fixtures.begin_request(room, "r1")
        begun = await self._begin(history, request)
        assert begun.user_message is not None
        output = self.fixtures.output(room, request)
        snapshot = self.fixtures.snapshot(request, begun.user_message, output)
        await history.stage_turn_result(
            StageTurnResultRequest(room=room, request_id="r1", output=output, snapshot=snapshot)
        )
        tampered = output.model_copy(update={"message": "다른 답변"})

        with pytest.raises(TurnStorageError):
            await history.complete_turn(
                CompleteTurnRequest(room=room, request_id="r1", output=tampered, snapshot=snapshot)
            )

    async def test_failed_turn_can_be_retried_with_same_user_message(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        request = self.fixtures.begin_request(room, "r1")
        first = await self._begin(history, request)
        await history.mark_turn_failed(
            MarkTurnFailedRequest(
                room=room,
                request_id="r1",
                failure_code=TurnFailureCode.GRAPH,
                detail="테스트 실패",
                retryable=True,
            )
        )

        retry = await self._begin(history, request)

        assert retry.status is TurnBeginStatus.NEW
        assert first.user_message is not None and retry.user_message is not None
        assert retry.user_message.message_id == first.user_message.message_id

    async def test_failed_turn_is_conflict_after_a_later_turn_completed(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        failed_request = self.fixtures.begin_request(room, "r1")
        await self._begin(history, failed_request)
        await history.mark_turn_failed(
            MarkTurnFailedRequest(
                room=room,
                request_id="r1",
                failure_code=TurnFailureCode.GRAPH,
                detail="테스트 실패",
                retryable=True,
            )
        )
        later_request = self.fixtures.begin_request(room, "r2")
        later = await self._begin(history, later_request)
        assert later.user_message is not None
        await self._complete(history, room, later_request, later.user_message)

        retry = await self._begin(history, failed_request)

        assert retry.status is TurnBeginStatus.CONFLICT

    async def test_stale_in_progress_turn_is_expired_so_room_is_not_blocked(
        self, session: AsyncSession, chat_room: ChatRoom
    ) -> None:
        factory = async_sessionmaker(
            bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        history = SqlAlchemyChatHistoryRepository(factory, stale_after=timedelta(seconds=30))
        room = self.fixtures.room(chat_room)
        await self._begin(history, self.fixtures.begin_request(room, "r1"))
        # 서버가 죽어 오래 갱신되지 않은 상태를 만든다
        await session.execute(
            text("UPDATE chat_turn_state SET updated_at = now() - interval '1 hour'")
        )

        result = await self._begin(history, self.fixtures.begin_request(room, "r2"))
        stale_retry = await self._begin(history, self.fixtures.begin_request(room, "r1"))

        assert result.status is TurnBeginStatus.NEW
        # r2가 진행 중이라 r1 재시도는 아직 막힌다
        assert stale_retry.status is TurnBeginStatus.IN_PROGRESS


class TestSessionContext:
    fixtures = ChatHistoryFixtures()

    async def _complete_turn(
        self,
        history: SqlAlchemyChatHistoryRepository,
        room: AuthorizedRoom,
        request_id: str,
        *,
        artifacts: list[ProductCandidateSet | RoutinePlan] | None = None,
        summary: ConversationSummary | None = None,
    ) -> BeginTurnRequest:
        request = self.fixtures.begin_request(room, request_id)
        begun = await history.begin_turn(request)
        assert begun.user_message is not None
        output = self.fixtures.output(room, request, artifacts=artifacts)
        snapshot = self.fixtures.snapshot(request, begun.user_message, output, summary=summary)
        stage = StageTurnResultRequest(
            room=room, request_id=request_id, output=output, snapshot=snapshot
        )
        await history.stage_turn_result(stage)
        await history.complete_turn(
            CompleteTurnRequest(room=room, request_id=request_id, output=output, snapshot=snapshot)
        )
        return request

    async def test_no_snapshot_before_first_completed_turn(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        await history.begin_turn(self.fixtures.begin_request(room, "r1"))

        result = await history.get_session_context(SessionContextRequest(room=room))

        assert result.snapshot is None

    async def test_snapshot_contains_completed_messages_and_increments_revision(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        await self._complete_turn(history, room, "r1")

        result = await history.get_session_context(SessionContextRequest(room=room))

        assert result.snapshot is not None
        assert result.snapshot.source_revision == 1
        assert result.snapshot.last_completed_request_id == "r1"
        assert [message.sequence for message in result.snapshot.messages] == [1, 2]

    async def test_failed_turn_message_is_not_in_snapshot(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        await self._complete_turn(history, room, "r1")
        await history.begin_turn(self.fixtures.begin_request(room, "r2"))
        await history.mark_turn_failed(
            MarkTurnFailedRequest(
                room=room,
                request_id="r2",
                failure_code=TurnFailureCode.GRAPH,
                detail="테스트 실패",
                retryable=False,
            )
        )

        result = await history.get_session_context(SessionContextRequest(room=room))

        assert result.snapshot is not None
        assert {message.request_id for message in result.snapshot.messages} == {"r1"}

    async def test_messages_covered_by_summary_are_left_out(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        await self._complete_turn(history, room, "r1")
        await self._complete_turn(
            history,
            room,
            "r2",
            summary=ConversationSummary(
                content="첫 대화 요약", version=1, covered_through_sequence=2
            ),
        )

        result = await history.get_session_context(SessionContextRequest(room=room))

        assert result.snapshot is not None
        assert [message.request_id for message in result.snapshot.messages] == ["r2", "r2"]

    async def test_get_messages_pages_with_has_more(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        await self._complete_turn(history, room, "r1")

        first_page = await history.get_messages(MessagePageRequest(room=room, limit=1))
        rest = await history.get_messages(
            MessagePageRequest(room=room, after_sequence=first_page.messages[0].sequence, limit=5)
        )

        assert first_page.has_more is True
        assert rest.has_more is False
        assert [message.sequence for message in rest.messages] == [2]

    async def test_artifacts_are_found_by_id_and_version(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        candidate_set = ProductCandidateSet(candidate_set_id="cs-1")
        routine = RoutinePlan(routine_id="routine-1", version=2, placements=[])
        await self._complete_turn(history, room, "r1", artifacts=[candidate_set, routine])

        by_candidate = await history.get_artifacts(
            ArtifactLookupRequest(room=room, candidate_set_id="cs-1")
        )
        by_routine = await history.get_artifacts(
            ArtifactLookupRequest(room=room, routine_id="routine-1", routine_version=2)
        )
        wrong_version = await history.get_artifacts(
            ArtifactLookupRequest(room=room, routine_id="routine-1", routine_version=3)
        )
        unknown = await history.get_artifacts(
            ArtifactLookupRequest(room=room, candidate_set_id="nope")
        )

        assert by_candidate.artifacts == [candidate_set]
        assert by_routine.artifacts == [routine]
        assert wrong_version.artifacts == []
        assert unknown.artifacts == []

    async def test_summary_save_uses_revision_as_optimistic_lock(
        self, history: SqlAlchemyChatHistoryRepository, chat_room: ChatRoom
    ) -> None:
        room = self.fixtures.room(chat_room)
        summary = ConversationSummary(content="요약", version=1, covered_through_sequence=1)
        before_any_turn = await history.save_summary(
            SaveSummaryRequest(room=room, summary=summary, expected_revision=0)
        )
        await self._complete_turn(history, room, "r1")

        stale = await history.save_summary(
            SaveSummaryRequest(room=room, summary=summary, expected_revision=0)
        )
        saved = await history.save_summary(
            SaveSummaryRequest(room=room, summary=summary, expected_revision=1)
        )

        assert before_any_turn.status is SummarySaveStatus.NO_SNAPSHOT
        assert stale.status is SummarySaveStatus.REVISION_CONFLICT
        assert stale.source_revision == 1
        assert saved.status is SummarySaveStatus.SAVED
        assert saved.source_revision == 2


class TestConcurrentTurns:
    """서로 다른 연결로 실제 commit하는 유일한 테스트. 방 잠금이 동시 요청을 직렬화하는지 본다."""

    fixtures = ChatHistoryFixtures()

    async def test_only_one_of_two_simultaneous_requests_starts(self) -> None:
        database = Database(settings.database)
        user_id: UUID | None = None
        try:
            async with database.session_factory() as setup, setup.begin():
                user = await self.fixtures.create_user(setup)
                user_id = user.id
                chat_room = await ChatRoomRepository(setup).get_or_create_for_user(user.id)
            history = SqlAlchemyChatHistoryRepository(database.session_factory)
            room = self.fixtures.room(chat_room)

            results = await asyncio.gather(
                history.begin_turn(self.fixtures.begin_request(room, "r1")),
                history.begin_turn(self.fixtures.begin_request(room, "r2")),
            )

            statuses = sorted(result.status.value for result in results)
            assert statuses == [TurnBeginStatus.IN_PROGRESS.value, TurnBeginStatus.NEW.value]
        finally:
            if user_id is not None:
                # FK CASCADE로 방·메시지·턴 상태가 함께 지워진다
                async with database.session_factory() as cleanup, cleanup.begin():
                    await cleanup.execute(delete(User).where(User.id == user_id))
            await database.dispose()
