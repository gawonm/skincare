"""`chat_message` 조회/저장. SQL은 이 계층에만 둔다. commit은 하지 않는다."""

from uuid import UUID

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.chat_message import ChatMessage, MessageRole
from models.chat_turn_state import ChatTurnState, TurnStateStatus


class ChatMessageRepository:
    """`chat_message` 한 테이블에 대한 조회/저장."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_sequence(self, room_id: UUID) -> int:
        """방 안의 다음 순번. 호출하는 쪽이 방 행을 잠근 상태여야 순번이 겹치지 않는다."""
        result = await self._session.execute(
            select(func.coalesce(func.max(ChatMessage.sequence), 0)).where(
                ChatMessage.chat_room_id == room_id
            )
        )
        return result.scalar_one() + 1

    async def add(
        self,
        *,
        message_id: UUID,
        room_id: UUID,
        request_id: str,
        role: MessageRole,
        content: str,
        sequence: int,
    ) -> ChatMessage:
        """Agent가 발급한 `message_id`를 그대로 PK로 저장한다."""
        message = ChatMessage(
            id=message_id,
            chat_room_id=room_id,
            request_id=request_id,
            role=role,
            content=content,
            sequence=sequence,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def get_by_request(
        self, room_id: UUID, request_id: str, role: MessageRole
    ) -> ChatMessage | None:
        result = await self._session.execute(
            select(ChatMessage).where(
                ChatMessage.chat_room_id == room_id,
                ChatMessage.request_id == request_id,
                ChatMessage.role == role,
            )
        )
        return result.scalar_one_or_none()

    async def list_after(self, room_id: UUID, after_sequence: int, limit: int) -> list[ChatMessage]:
        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_room_id == room_id, ChatMessage.sequence > after_sequence)
            .order_by(ChatMessage.sequence)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_completed_after(self, room_id: UUID, after_sequence: int) -> list[ChatMessage]:
        """확정된 턴의 메시지만 순번 순으로 돌려준다.

        실패한 턴이 남긴 사용자 메시지를 세션 스냅샷에 섞으면, 사용자가 재시도하지 않은 질문이
        다음 대화의 문맥으로 들어간다.
        """
        result = await self._session.execute(
            select(ChatMessage)
            .join(
                ChatTurnState,
                and_(
                    ChatTurnState.chat_room_id == ChatMessage.chat_room_id,
                    ChatTurnState.request_id == ChatMessage.request_id,
                ),
            )
            .where(
                ChatMessage.chat_room_id == room_id,
                ChatMessage.sequence > after_sequence,
                ChatTurnState.status == TurnStateStatus.COMPLETED,
            )
            .order_by(ChatMessage.sequence)
        )
        return list(result.scalars().all())

    async def has_completed_after(self, room_id: UUID, sequence: int) -> bool:
        """이 순번보다 뒤에 확정된 메시지가 있는지. 실패한 턴을 재시도해도 되는지 판단할 때 쓴다."""
        completed_after = (
            select(ChatMessage.id)
            .join(
                ChatTurnState,
                and_(
                    ChatTurnState.chat_room_id == ChatMessage.chat_room_id,
                    ChatTurnState.request_id == ChatMessage.request_id,
                ),
            )
            .where(
                ChatMessage.chat_room_id == room_id,
                ChatMessage.sequence > sequence,
                ChatTurnState.status == TurnStateStatus.COMPLETED,
            )
        )
        result = await self._session.execute(select(exists(completed_after)))
        return bool(result.scalar_one())
