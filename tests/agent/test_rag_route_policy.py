from agent.rag_route_policy import RagRoutePolicy, RagRouteReason
from agent.schemas import Intent, IntentQueryPlan, ParsedRequest, RagRoute


class TestRagRoutePolicy:
    def test_성분이_없는_피부고민_Evidence_질의는_Case_탐색을_보존한다(self) -> None:
        request = ParsedRequest(
            intents=[Intent.EVIDENCE_QA],
            query=(
                "여드름 제품을 쓰면 뾰루지는 줄지만 얼굴이 따갑고 각질이 생깁니다. "
                "계속 사용해도 될까요?"
            ),
            query_plan=IntentQueryPlan(
                case_query="여드름 제품 사용 후 따가움과 각질",
                evidence_query="여드름 제품 사용 중 따가움과 각질 주의사항",
            ),
            skin_concerns=["여드름", "따가움", "각질"],
            rag_route=RagRoute.EVIDENCE_ONLY,
        )

        decision = RagRoutePolicy().decide(request)

        assert decision.route is RagRoute.CLAIM_THEN_EVIDENCE
        assert decision.reason is RagRouteReason.UNSPECIFIED_INGREDIENT_CONCERN
        assert decision.normalized_intents == [Intent.EVIDENCE_QA]
        assert decision.normalized_skin_concerns == ["여드름", "따가움", "각질"]

    def test_처짐_한계_질문도_Case_질의_초안이_있으면_Case_탐색을_보존한다(
        self,
    ) -> None:
        request = ParsedRequest(
            intents=[Intent.EVIDENCE_QA],
            query=(
                "41살이고 볼과 턱선 처짐이 신경 쓰입니다. "
                "화장품이 실제로 도울 수 있는 범위와 한계를 알고 싶어요."
            ),
            query_plan=IntentQueryPlan(
                case_query="41살, 볼과 턱선 처짐",
                evidence_query="화장품이 처짐에 도울 수 있는 범위와 한계",
            ),
            skin_concerns=["볼과 턱선 처짐"],
            rag_route=RagRoute.EVIDENCE_ONLY,
        )

        decision = RagRoutePolicy().decide(request)

        assert decision.route is RagRoute.CLAIM_THEN_EVIDENCE
        assert decision.reason is RagRouteReason.UNSPECIFIED_INGREDIENT_CONCERN

    def test_명시_성분의_Evidence_질문은_직행을_유지한다(self) -> None:
        request = ParsedRequest(
            intents=[Intent.EVIDENCE_QA],
            query="민감한 피부에 나이아신아마이드를 써도 될까요?",
            query_plan=IntentQueryPlan(
                case_query="민감한 피부",
                evidence_query="나이아신아마이드 민감 피부 주의사항",
            ),
            ingredient_mentions=["나이아신아마이드"],
            skin_concerns=["민감"],
            rag_route=RagRoute.EVIDENCE_ONLY,
        )

        decision = RagRoutePolicy().decide(request)

        assert decision.route is RagRoute.EVIDENCE_ONLY
        assert decision.reason is RagRouteReason.EXPLICIT_EVIDENCE_REQUEST

    def test_성분이_없는_피부고민_루틴은_Case_탐색을_보존한다(self) -> None:
        request = ParsedRequest(
            intents=[Intent.ROUTINE_PLANNING],
            query=(
                "30살 남성이고 면도하는 턱선에 여드름과 따가움이 반복됩니다. "
                "자극을 줄이는 루틴이 필요합니다."
            ),
            query_plan=IntentQueryPlan(
                case_query="30살 남성 면도 부위 여드름과 따가움",
                routine_query="자극을 줄이는 루틴",
            ),
            skin_concerns=["여드름", "따가움"],
            rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
        )

        decision = RagRoutePolicy().decide(request)

        assert decision.route is RagRoute.CLAIM_THEN_EVIDENCE
        assert decision.reason is RagRouteReason.UNSPECIFIED_INGREDIENT_CONCERN

    def test_명시_성분_상품_질문은_Case_탐색을_우회한다(self) -> None:
        request = ParsedRequest(
            intents=[Intent.PRODUCT_DISCOVERY],
            query="건조하고 따가운 피부인데 레티놀 제품을 시작하고 싶어요.",
            query_plan=IntentQueryPlan(
                case_query="건조하고 따가운 피부의 레티놀 제품",
                product_query="레티놀 제품",
            ),
            ingredient_mentions=["레티놀"],
            skin_concerns=["건조", "따가움"],
            rag_route=RagRoute.CLAIM_THEN_EVIDENCE,
        )

        decision = RagRoutePolicy().decide(request)

        assert decision.route is None
        assert decision.reason is RagRouteReason.EXPLICIT_INGREDIENT_PRODUCT

    def test_Case_질의_초안이_없는_일반_Evidence_질문은_직행을_유지한다(
        self,
    ) -> None:
        request = ParsedRequest(
            intents=[Intent.EVIDENCE_QA],
            query="건조한 피부가 생기는 일반적인 이유는 무엇인가요?",
            query_plan=IntentQueryPlan(
                evidence_query="건조 피부의 일반적인 원인"
            ),
            skin_concerns=["건조"],
            rag_route=RagRoute.EVIDENCE_ONLY,
        )

        decision = RagRoutePolicy().decide(request)

        assert decision.route is RagRoute.EVIDENCE_ONLY
        assert decision.reason is RagRouteReason.EXPLICIT_EVIDENCE_REQUEST
