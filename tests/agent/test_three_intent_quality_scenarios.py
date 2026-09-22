"""핵심 세 Intent를 사용자 표현별로 반복 검증하는 품질 회귀 테스트."""

from collections import Counter
from enum import StrEnum

import pytest
from pydantic import Field

from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.rag.schemas import ProductCandidateSet, RoutinePlan, Weekday
from agent.schemas import (
    AgentModel,
    AuthenticatedChatContext,
    ChatServiceRequest,
    ChatStatus,
    ChatTurnInput,
    ChatTurnOutput,
    Intent,
    RegisterRoomRequest,
)


class ExpectedArtifact(StrEnum):
    PRODUCT_CANDIDATES = "product_candidates"
    ROUTINE = "routine"
    NONE = "none"


class IntentQualityScenario(AgentModel):
    scenario_id: str = Field(min_length=1)
    intent: Intent
    message: str = Field(min_length=1)
    expected_status: ChatStatus
    expected_artifact: ExpectedArtifact
    setup_messages: list[str] = Field(default_factory=list)
    expected_product_id: str | None = None
    expected_excluded_weekday: Weekday | None = None
    requires_citation: bool = False
    requires_follow_up: bool = False


class IntentQualityScenarioCatalog:
    """의도마다 서로 다른 진입 조건을 세 개씩 고정해 회귀 범위를 명시한다."""

    @classmethod
    def build(cls) -> list[IntentQualityScenario]:
        return [
            IntentQualityScenario(
                scenario_id="product-concern-case-rag",
                intent=Intent.PRODUCT_DISCOVERY,
                message="피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?",
                expected_status=ChatStatus.PARTIAL,
                expected_artifact=ExpectedArtifact.PRODUCT_CANDIDATES,
                expected_product_id="product:niacinamide-serum",
            ),
            IntentQualityScenario(
                scenario_id="product-filtered-texture",
                intent=Intent.PRODUCT_DISCOVERY,
                message="가벼운 보습 크림 추천해줘",
                expected_status=ChatStatus.COMPLETED,
                expected_artifact=ExpectedArtifact.PRODUCT_CANDIDATES,
                expected_product_id="product:panthenol-gel",
            ),
            IntentQualityScenario(
                scenario_id="product-explicit-ingredient",
                intent=Intent.PRODUCT_DISCOVERY,
                message="나이아신아마이드 제품 추천해줘",
                expected_status=ChatStatus.COMPLETED,
                expected_artifact=ExpectedArtifact.PRODUCT_CANDIDATES,
                expected_product_id="product:niacinamide-serum",
            ),
            IntentQualityScenario(
                scenario_id="evidence-efficacy",
                intent=Intent.EVIDENCE_QA,
                message="나이아신아마이드 효능과 근거를 알려줘",
                expected_status=ChatStatus.COMPLETED,
                expected_artifact=ExpectedArtifact.NONE,
                requires_citation=True,
            ),
            IntentQualityScenario(
                scenario_id="evidence-precaution",
                intent=Intent.EVIDENCE_QA,
                message="레티놀을 사용할 때 주의할 점과 근거를 알려줘",
                expected_status=ChatStatus.COMPLETED,
                expected_artifact=ExpectedArtifact.NONE,
                requires_citation=True,
            ),
            IntentQualityScenario(
                scenario_id="evidence-combination",
                intent=Intent.EVIDENCE_QA,
                message="나이아신아마이드와 레티놀을 같이 써도 괜찮아?",
                expected_status=ChatStatus.COMPLETED,
                expected_artifact=ExpectedArtifact.NONE,
                requires_citation=True,
            ),
            IntentQualityScenario(
                scenario_id="routine-missing-products",
                intent=Intent.ROUTINE_PLANNING,
                message="이 제품들로 저녁 루틴을 어떻게 짜면 돼?",
                expected_status=ChatStatus.NEEDS_INPUT,
                expected_artifact=ExpectedArtifact.NONE,
                requires_follow_up=True,
            ),
            IntentQualityScenario(
                scenario_id="routine-explicit-products",
                intent=Intent.ROUTINE_PLANNING,
                message="데모 세라마이드 크림과 데모 판테놀 젤 크림으로 저녁 루틴 짜줘",
                expected_status=ChatStatus.COMPLETED,
                expected_artifact=ExpectedArtifact.ROUTINE,
            ),
            IntentQualityScenario(
                scenario_id="routine-modification",
                intent=Intent.ROUTINE_PLANNING,
                setup_messages=[
                    "데모 세라마이드 크림과 데모 판테놀 젤 크림으로 저녁 루틴 짜줘"
                ],
                message="월요일은 빼줘",
                expected_status=ChatStatus.COMPLETED,
                expected_artifact=ExpectedArtifact.ROUTINE,
                expected_excluded_weekday=Weekday.MONDAY,
            ),
        ]


class IntentQualityHarness:
    def create(self, scenario: IntentQualityScenario) -> DevelopmentAgentApplication:
        application = DevelopmentAgentFactory().create()
        application.history.register_room(
            RegisterRoomRequest(
                actor_id="quality-user",
                chat_room_id=scenario.scenario_id,
                thread_id=f"thread:{scenario.scenario_id}",
            )
        )
        return application

    async def run(self, scenario: IntentQualityScenario) -> ChatTurnOutput:
        application = self.create(scenario)
        for index, setup_message in enumerate(scenario.setup_messages, start=1):
            setup_output = await application.service.handle_turn(
                self.request(
                    scenario=scenario,
                    request_id=f"setup-{index}",
                    message=setup_message,
                )
            )
            if setup_output.status is not ChatStatus.COMPLETED:
                raise AssertionError(
                    f"{scenario.scenario_id} 준비 요청 실패: {setup_output.status.value}"
                )
        return await application.service.handle_turn(
            self.request(
                scenario=scenario,
                request_id="target",
                message=scenario.message,
            )
        )

    def request(
        self,
        scenario: IntentQualityScenario,
        request_id: str,
        message: str,
    ) -> ChatServiceRequest:
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(
                actor_id="quality-user",
                chat_room_id=scenario.scenario_id,
            ),
            turn=ChatTurnInput(
                chat_room_id=scenario.scenario_id,
                request_id=request_id,
                message=message,
            ),
        )


class TestThreeIntentQualityScenarios:
    def test_각_핵심_의도는_정확히_세_시나리오를_갖는다(self) -> None:
        counts = Counter(scenario.intent for scenario in IntentQualityScenarioCatalog.build())

        assert counts == {
            Intent.PRODUCT_DISCOVERY: 3,
            Intent.EVIDENCE_QA: 3,
            Intent.ROUTINE_PLANNING: 3,
        }

    @pytest.mark.parametrize(
        "scenario",
        IntentQualityScenarioCatalog.build(),
        ids=[scenario.scenario_id for scenario in IntentQualityScenarioCatalog.build()],
    )
    async def test_의도별_대표_요청이_예상_결과까지_도달한다(
        self,
        scenario: IntentQualityScenario,
    ) -> None:
        output = await IntentQualityHarness().run(scenario)

        assert output.intents == [scenario.intent]
        assert output.status is scenario.expected_status
        assert bool(output.citations) is scenario.requires_citation
        assert (output.follow_up_question is not None) is scenario.requires_follow_up
        self._assert_artifact(output, scenario)

    def _assert_artifact(
        self,
        output: ChatTurnOutput,
        scenario: IntentQualityScenario,
    ) -> None:
        product_sets = [
            artifact
            for artifact in output.artifacts
            if isinstance(artifact, ProductCandidateSet)
        ]
        routines = [
            artifact for artifact in output.artifacts if isinstance(artifact, RoutinePlan)
        ]

        if scenario.expected_artifact is ExpectedArtifact.PRODUCT_CANDIDATES:
            assert product_sets
            assert routines == []
            if scenario.expected_product_id is not None:
                product_ids = {
                    candidate.product.product_id
                    for candidate_set in product_sets
                    for candidate in candidate_set.candidates
                }
                assert scenario.expected_product_id in product_ids
            return

        if scenario.expected_artifact is ExpectedArtifact.ROUTINE:
            assert routines
            assert product_sets == []
            if scenario.expected_excluded_weekday is not None:
                assert all(
                    placement.weekday is not scenario.expected_excluded_weekday
                    for routine in routines
                    for placement in routine.placements
                )
            return

        assert product_sets == []
        assert routines == []
