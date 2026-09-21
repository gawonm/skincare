"""`chat_room` 조회/저장. SQL은 이 계층에만 둔다. commit은 하지 않는다.

Agent DTO(`SessionSnapshot` 등)를 import하지 않는다. `repositories/`는 `models`만 import한다는
규칙이라, 호출하는 `services/`가 JSON 값으로 바꿔 `ChatRoomSnapshotUpdate`에 담아 넘긴다.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.chat_room import ChatRoom


class ChatRoomSnapshotUpdate(BaseModel):
    """`chat_room`의 세션 스냅샷 컬럼 묶음. JSONB에 그대로 넣을 JSON 값만 담는다."""

    model_config = ConfigDict(frozen=True)

    schema_version: int
    source_revision: int
    last_completed_request_id: str | None
    profile: dict[str, JsonValue]
    task_context: dict[str, JsonValue]
    pending_question: dict[str, JsonValue] | None
    candidate_set: dict[str, JsonValue] | None
    routine: dict[str, JsonValue] | None
    evidence: list[JsonValue]
    summary: dict[str, JsonValue] | None


class ChatRoomRepository:
    """`chat_room` 한 테이블에 대한 조회/저장. 트랜잭션 경계는 호출하는 서비스가 정한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, room_id: UUID) -> ChatRoom | None:
        result = await self._session.execute(select(ChatRoom).where(ChatRoom.id == room_id))
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, room_id: UUID) -> ChatRoom | None:
        """방 행을 잠근다. 같은 방의 턴 시작·확정을 한 번에 하나씩만 처리하려는 것이다."""
        result = await self._session.execute(
            select(ChatRoom).where(ChatRoom.id == room_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: UUID) -> ChatRoom | None:
        result = await self._session.execute(select(ChatRoom).where(ChatRoom.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create_for_user(self, user_id: UUID) -> ChatRoom:
        """사용자당 방 1개를 돌려주고 없으면 만든다.

        동시에 두 요청이 와도 `user_id` UNIQUE 때문에 한쪽 INSERT는 아무것도 하지 않고, 두 요청 모두
        같은 방을 읽는다. 조회 후 INSERT 순서로 쓰면 이 경합에서 UNIQUE 위반 예외가 난다.
        """
        await self._session.execute(
            insert(ChatRoom)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        room = await self.get_by_user_id(user_id)
        if room is None:
            raise RuntimeError(f"채팅방을 만들거나 찾지 못했습니다: user_id={user_id}")
        return room

    async def apply_snapshot(self, room: ChatRoom, update: ChatRoomSnapshotUpdate) -> None:
        """턴이 확정될 때 스냅샷 컬럼을 한 번에 덮어쓴다."""
        room.schema_version = update.schema_version
        room.source_revision = update.source_revision
        room.last_completed_request_id = update.last_completed_request_id
        room.profile = update.profile
        room.task_context = update.task_context
        room.pending_question = update.pending_question
        room.candidate_set = update.candidate_set
        room.routine = update.routine
        room.evidence = update.evidence
        room.summary = update.summary
        await self._session.flush()

    async def save_summary(self, room: ChatRoom, summary: dict[str, JsonValue]) -> int:
        """요약만 바꾸고 `source_revision`을 올린다. 새 revision을 돌려준다."""
        room.summary = summary
        room.source_revision = room.source_revision + 1
        await self._session.flush()
        return room.source_revision
