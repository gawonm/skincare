"""`/chat` 엔드포인트. HTTP만 다루고 업무 로직은 `ChatTurnService`에 맡긴다."""

from fastapi import APIRouter

from backend.api.dependencies import ChatTurnServiceDep, CurrentUserDep
from backend.schemas.chat import ChatSendMessageRequest, ChatTurnResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatTurnResponse)
async def send_message(
    body: ChatSendMessageRequest,
    user: CurrentUserDep,
    service: ChatTurnServiceDep,
) -> ChatTurnResponse:
    """로그인 사용자의 채팅방에 메시지 한 턴을 보내고 Agent 응답을 돌려준다."""
    return await service.send_message(user.id, body)
