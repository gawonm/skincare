"""역할 누락과 번호 기반 루틴이 최종 사용자 응답까지 유지되는지 검증한다."""

from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.rag.schemas import DayPeriod, RoutinePlan
from agent.schemas import (
    AuthenticatedChatContext,
    ChatServiceRequest,
    ChatStatus,
    ChatTurnInput,
    RegisterRoomRequest,
)


class RoleBasedRoutineFlowHarness:
    def create(self) -> DevelopmentAgentApplication:
        application = DevelopmentAgentFactory().create()
        application.history.register_room(
            RegisterRoomRequest(
                actor_id="user-a",
                chat_room_id="room-a",
                thread_id="thread-role-based-routine",
            )
        )
        return application

    def request(self, request_id: str, message: str) -> ChatServiceRequest:
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(
                actor_id="user-a",
                chat_room_id="room-a",
            ),
            turn=ChatTurnInput(
                chat_room_id="room-a",
                request_id=request_id,
                message=message,
            ),
        )


class TestRoleBasedRoutineFlow:
    async def test_단독_3회는_요일과_시간대를_만들지_않고_루틴_번호로_표시한다(
        self,
    ) -> None:
        harness = RoleBasedRoutineFlowHarness()
        application = harness.create()

        output = await application.service.handle_turn(
            harness.request(
                "standalone-count",
                "데모 세라마이드 크림으로 3회 루틴 짜줘",
            )
        )
        plan = next(
            artifact for artifact in output.artifacts if isinstance(artifact, RoutinePlan)
        )

        assert output.status is ChatStatus.COMPLETED
        assert "루틴 1:" in output.message
        assert "루틴 3:" in output.message
        assert "월요일" not in output.message
        assert "아침" not in output.message
        assert "저녁" not in output.message
        assert "(세안 상품: 이번 검색 결과에서 후보 없음)" in output.message
        assert "(케어 상품: 이번 검색 결과에서 후보 없음)" in output.message
        assert {placement.period for placement in plan.placements} == {
            DayPeriod.UNSPECIFIED
        }

    async def test_3일간과_명시한_저녁은_일차와_시간대로_표시한다(self) -> None:
        harness = RoleBasedRoutineFlowHarness()
        application = harness.create()

        output = await application.service.handle_turn(
            harness.request(
                "duration-with-period",
                "데모 세라마이드 크림으로 저녁 3일간 루틴 짜줘",
            )
        )
        plan = next(
            artifact for artifact in output.artifacts if isinstance(artifact, RoutinePlan)
        )

        assert "1일차:" in output.message
        assert "3일차:" in output.message
        assert "저녁 데모 세라마이드 크림" in output.message
        assert {placement.period for placement in plan.placements} == {
            DayPeriod.EVENING
        }
