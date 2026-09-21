"""`ChatRoomService`를 실제 로컬 DB로 검증한다.

방 생성 동시성은 서로 다른 연결이 필요해서 실제로 commit하고 마지막에 계정을 지워(FK CASCADE)
정리한다. 나머지는 `session` 픽스처의 SAVEPOINT 위에서 돌아 데이터가 남지 않는다.
"""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.schemas.chat import ChatSendMessageRequest
from backend.services.chat_room import ChatRoomService
from core.config import settings
from core.database import Database
from models.chat_room import ChatRoom
from models.user import User
from tests.db.test_chat_history import ChatHistoryFixtures


@pytest.fixture
def rooms(session: AsyncSession) -> ChatRoomService:
    factory = async_sessionmaker(
        bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    return ChatRoomService(factory)


class TestChatRoomService:
    fixtures = ChatHistoryFixtures()

    async def test_first_call_creates_room_and_second_call_reuses_it(
        self, session: AsyncSession, rooms: ChatRoomService
    ) -> None:
        user = await self.fixtures.create_user(session)

        first = await rooms.ensure_room(user.id)
        second = await rooms.ensure_room(user.id)

        count = await session.scalar(
            select(func.count()).select_from(ChatRoom).where(ChatRoom.user_id == user.id)
        )
        assert first == second
        assert first.actor_id == str(user.id)
        assert count == 1

    async def test_different_users_get_different_rooms(
        self, session: AsyncSession, rooms: ChatRoomService
    ) -> None:
        first_user = await self.fixtures.create_user(session)
        second_user = await self.fixtures.create_user(session)

        first = await rooms.ensure_room(first_user.id)
        second = await rooms.ensure_room(second_user.id)

        assert first.chat_room_id != second.chat_room_id
        assert first.thread_id != second.thread_id

    async def test_prepare_request_fills_room_and_actor_from_server(
        self, session: AsyncSession, rooms: ChatRoomService
    ) -> None:
        user = await self.fixtures.create_user(session)

        request = await rooms.prepare_request(
            user.id,
            ChatSendMessageRequest(
                request_id="r1",
                message="레티놀 써도 돼?",
                candidate_set_id="cs-1",
                routine_version=2,
            ),
        )

        room = await rooms.ensure_room(user.id)
        assert request.auth.actor_id == str(user.id)
        assert request.auth.chat_room_id == room.chat_room_id
        assert request.turn.chat_room_id == room.chat_room_id
        assert request.turn.request_id == "r1"
        assert request.turn.message == "레티놀 써도 돼?"
        assert request.turn.candidate_set_id == "cs-1"
        assert request.turn.routine_version == 2


class TestConcurrentRoomCreation:
    """서로 다른 연결로 실제 commit하는 테스트. UNIQUE 경합에서도 같은 방을 돌려주는지 본다."""

    fixtures = ChatHistoryFixtures()

    async def test_simultaneous_first_calls_return_the_same_room(self) -> None:
        database = Database(settings.database)
        user_id: UUID | None = None
        try:
            async with database.session_factory() as setup, setup.begin():
                user_id = (await self.fixtures.create_user(setup)).id
            rooms = ChatRoomService(database.session_factory)

            results = await asyncio.gather(*(rooms.ensure_room(user_id) for _ in range(5)))

            async with database.session_factory() as check:
                count = await check.scalar(
                    select(func.count()).select_from(ChatRoom).where(ChatRoom.user_id == user_id)
                )
            assert len({room.chat_room_id for room in results}) == 1
            assert count == 1
        finally:
            if user_id is not None:
                # FK CASCADE로 방도 함께 지워진다
                async with database.session_factory() as cleanup, cleanup.begin():
                    await cleanup.execute(delete(User).where(User.id == user_id))
            await database.dispose()
