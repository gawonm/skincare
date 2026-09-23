from agent.schemas import Intent, ParsedRequest, RagRoute
from agent.task_planning import TaskPlanBuilder


class TestTaskPlanBuilder:
    def test_상품보다_먼저_반환된_루틴을_의존성_순서로_정렬한다(self) -> None:
        request = ParsedRequest(
            intents=[Intent.ROUTINE_PLANNING, Intent.PRODUCT_DISCOVERY],
            query="추천 상품으로 4회 루틴을 짜줘",
            rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
        )

        assert TaskPlanBuilder().build(request) == [
            Intent.EVIDENCE_QA,
            Intent.PRODUCT_DISCOVERY,
            Intent.ROUTINE_PLANNING,
        ]

    def test_루틴_저장은_루틴_계획_뒤로_정렬한다(self) -> None:
        request = ParsedRequest(
            intents=[
                Intent.ROUTINE_SAVE,
                Intent.ROUTINE_PLANNING,
                Intent.PRODUCT_DISCOVERY,
            ],
            query="추천 상품으로 루틴을 만들고 저장해줘",
        )

        assert TaskPlanBuilder().build(request) == [
            Intent.PRODUCT_DISCOVERY,
            Intent.ROUTINE_PLANNING,
            Intent.ROUTINE_SAVE,
        ]

    def test_의존성이_없는_Intent의_상대_순서는_보존한다(self) -> None:
        request = ParsedRequest(
            intents=[Intent.GENERAL_CHAT, Intent.OUT_OF_SCOPE],
            query="테스트",
        )

        assert TaskPlanBuilder().build(request) == [
            Intent.GENERAL_CHAT,
            Intent.OUT_OF_SCOPE,
        ]
