"""유료 API와 DB 없이 두 채팅방 격리를 확인하는 실행 예제."""

import asyncio

from agent.factory import DevelopmentAgentFactory
from agent.schemas import (
    AuthenticatedChatContext,
    ChatServiceRequest,
    ChatTurnInput,
    ChatTurnOutput,
    RegisterRoomRequest,
)


class DemoApplication:
    """후보 생성과 후속 참조를 실제 그래프 호출로 보여준다."""

    async def run(self) -> list[ChatTurnOutput]:
        application = DevelopmentAgentFactory().create()
        application.history.register_room(
            RegisterRoomRequest(actor_id="demo-user", chat_room_id="room-a", thread_id="room-a")
        )
        application.history.register_room(
            RegisterRoomRequest(actor_id="demo-user", chat_room_id="room-b", thread_id="room-b")
        )

        requests = [
            self._request("room-a", "request-a1", "가벼운 보습 크림 추천해줘"),
            self._request("room-a", "request-a2", "1번으로 일정 짜줘"),
            self._request("room-b", "request-b1", "나이아신아마이드 역할과 근거를 알려줘"),
        ]
        outputs: list[ChatTurnOutput] = []
        for request in requests:
            outputs.append(await application.service.handle_turn(request))
        return outputs

    async def run_and_print(self) -> None:
        for output in await self.run():
            print(output.model_dump_json(indent=2))

    def _request(
        self,
        chat_room_id: str,
        request_id: str,
        message: str,
    ) -> ChatServiceRequest:
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(
                actor_id="demo-user",
                chat_room_id=chat_room_id,
            ),
            turn=ChatTurnInput(
                chat_room_id=chat_room_id,
                request_id=request_id,
                message=message,
            ),
        )


if __name__ == "__main__":
    asyncio.run(DemoApplication().run_and_print())
