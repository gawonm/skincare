"""로그인 사용자의 채팅방을 준비하고 Agent 호출 요청을 조립한다.

사용자당 방이 1개라 클라이언트는 방 식별자를 보내지 않는다. 서버가 로그인 사용자로 방을 찾고(없으면
만들고), 그 값을 Agent 요청에 채운다. 방 생성은 자기 트랜잭션으로 바로 커밋한다. 그래야 뒤이어 Agent가
히스토리 저장소로 그 방을 조회할 때 이미 보인다.
"""

from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.schemas import (
    AuthenticatedChatContext,
    AuthorizedRoom,
    ChatServiceRequest,
    ChatTurnInput,
)
from backend.repositories.chat_room_repository import ChatRoomRepository
from backend.schemas.chat import ChatSendMessageRequest


class ChatRoomService:
    """사용자, 채팅방, Agent 요청 순서로 값을 채운다."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_room(self, user_id: UUID) -> AuthorizedRoom:
        """사용자의 방을 돌려주고 없으면 만든다. 동시에 호출돼도 같은 방을 돌려준다."""
        try:
            async with self._session_factory() as session, session.begin():
                room = await ChatRoomRepository(session).get_or_create_for_user(user_id)
                return AuthorizedRoom(
                    actor_id=str(user_id),
                    chat_room_id=str(room.id),
                    thread_id=str(room.thread_id),
                )
        except SQLAlchemyError as error:
            raise RuntimeError(
                f"채팅방을 준비하지 못했습니다: user_id={user_id}: {error}"
            ) from error

    async def prepare_request(
        self, user_id: UUID, request: ChatSendMessageRequest
    ) -> ChatServiceRequest:
        """HTTP 요청을 Agent 요청으로 바꾼다. 방 식별자와 사용자는 서버가 채운다."""
        room = await self.ensure_room(user_id)
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(actor_id=room.actor_id, chat_room_id=room.chat_room_id),
            turn=ChatTurnInput(
                chat_room_id=room.chat_room_id,
                request_id=request.request_id,
                message=request.message,
                candidate_set_id=request.candidate_set_id,
                routine_version=request.routine_version,
            ),
        )
