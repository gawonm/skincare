from agent.query_planning import IntentQueryPlanner
from agent.schemas import (
    Intent,
    IntentQueryPlan,
    ParsedRequest,
    QueryPlanningRequest,
    RagRoute,
)


class TestIntentQueryPlanner:
    def test_복합_요청에서_Case_문맥을_보존하고_루틴_지시를_분리한다(self) -> None:
        original = (
            "30대 남성, 요즘 환절기여서 힘들다. 여드름이 자꾸 올라오는 지성 피부인데 "
            "어떤 성분이 좋고 주의할 점은 뭐야? 추천 상품으로 3일간 스킨케어 루틴 짜줘"
        )
        parsed = ParsedRequest(
            intents=[
                Intent.PRODUCT_DISCOVERY,
                Intent.ROUTINE_PLANNING,
                Intent.EVIDENCE_QA,
            ],
            query="여드름 지성 피부에 좋은 성분과 주의점 및 3일 스킨케어 루틴",
            query_plan=IntentQueryPlan(
                case_query="여드름 지성 피부에 좋은 성분과 주의사항",
                evidence_query="여드름 지성 피부 성분의 효능과 주의사항",
                product_query="검증된 추천 성분을 포함하는 상품",
                routine_query="추천 상품으로 3일간 스킨케어 루틴 구성",
            ),
            skin_concerns=["여드름", "지성 피부"],
            rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
        )

        result = IntentQueryPlanner().build(
            QueryPlanningRequest(
                original_message=original,
                parsed_request=parsed,
            )
        )

        assert result.case_query == (
            "30대 남성 환절기 여드름 지성 피부에 좋은 성분과 주의사항"
        )
        assert "상품" not in result.case_query
        assert "루틴" not in result.case_query
        assert result.product_query == "검증된 추천 성분을 포함하는 상품"
        assert result.routine_query == "추천 상품으로 3일간 스킨케어 루틴 구성"

    def test_Case_질의에_이미_있는_피부_고민을_중복해서_붙이지_않는다(self) -> None:
        parsed = ParsedRequest(
            intents=[Intent.PRODUCT_DISCOVERY],
            query="피지가 많고 여드름이 나는 지성 피부에 좋은 성분은?",
            query_plan=IntentQueryPlan(
                case_query="피지가 많고 여드름이 나는 지성 피부에 좋은 성분은?"
            ),
            skin_concerns=["피지", "여드름", "지성"],
            rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
        )

        result = IntentQueryPlanner().build(
            QueryPlanningRequest(
                original_message=parsed.query,
                parsed_request=parsed,
            )
        )

        assert result.case_query == parsed.query

    def test_명시_성분_Evidence_직행에는_Case_질의를_만들지_않는다(self) -> None:
        parsed = ParsedRequest(
            intents=[Intent.EVIDENCE_QA],
            query="나이아신아마이드 효능과 주의사항",
            query_plan=IntentQueryPlan(
                evidence_query="나이아신아마이드 효능과 주의사항"
            ),
            ingredient_mentions=["나이아신아마이드"],
            rag_route=RagRoute.EVIDENCE_ONLY,
        )

        result = IntentQueryPlanner().build(
            QueryPlanningRequest(
                original_message=parsed.query,
                parsed_request=parsed,
            )
        )

        assert result.case_query is None
        assert result.evidence_query == parsed.query
