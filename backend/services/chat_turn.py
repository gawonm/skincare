"""채팅 한 턴을 처리한다: 방 준비, Agent 호출, HTTP 응답 변환.

Agent 오류(`ROOM_FORBIDDEN`, `REQUEST_CONFLICT` 등)는 Agent가 `ChatTurnOutput`의 `status`와
`error_code`로 돌려준다. Agent 타입의 의미를 바꾸지 않으려고(`backend-to-agent.md` 6절) 이 서비스는
그것을 예외로 바꾸지 않고 그대로 응답 본문에 싣는다. HTTP 상태 코드는 로그인 안 함(401)과 요청
검증 실패(422)에만 쓴다.
"""

from uuid import UUID

from agent.schemas import ChatTurnOutput
from agent.service import ChatService
from backend.schemas.chat import ChatSendMessageRequest, ChatTurnResponse
from backend.services.chat_room import ChatRoomService


class ChatTurnService:
    """로그인 사용자의 메시지 한 건을 Agent에 넘기고 응답을 돌려준다."""

    def __init__(self, rooms: ChatRoomService, agent: ChatService) -> None:
        self._rooms = rooms
        self._agent = agent

    async def send_message(
        self, user_id: UUID, request: ChatSendMessageRequest
    ) -> ChatTurnResponse:
        agent_request = await self._rooms.prepare_request(user_id, request)
        output = await self._agent.handle_turn(agent_request)
        return self._to_response(output)

    def _to_response(self, output: ChatTurnOutput) -> ChatTurnResponse:
        return ChatTurnResponse(
            chat_room_id=output.chat_room_id,
            request_id=output.request_id,
            assistant_message_id=output.assistant_message_id,
            status=output.status,
            message=output.message,
            intents=output.intents,
            follow_up_question=output.follow_up_question,
            artifacts=output.artifacts,
            citations=output.citations,
            unresolved=output.unresolved,
            error_code=output.error_code,
            retryable=output.retryable,
            save_handoff=output.save_handoff,
        )
