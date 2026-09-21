"""LLM Rule 후보와 루틴 초안의 결정적 방어 계층 검증."""

from agent.ports import RoutineDraftGenerator, RoutineRuleGenerator
from agent.rag.routine_planner import SourceBoundRoutinePlanner
from agent.rag.schemas import (
    CaseUsageGuidance,
    ConstraintSource,
    DayPeriod,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSourceType,
    EvidenceTextKind,
    ProductRecord,
    RoutineDraftGenerationRequest,
    RoutineDraftModelOutput,
    RoutineDraftPlacement,
    RoutinePlanRequest,
    RoutineRuleCandidate,
    RoutineRuleEnforcement,
    RoutineRuleGenerationRequest,
    RoutineRuleModelOutput,
    RoutineRuleSourceKind,
    RoutineRuleType,
    RoutineValidationRequest,
    Weekday,
)


class FixedRoutineRuleGenerator(RoutineRuleGenerator):
    def __init__(self, output: RoutineRuleModelOutput) -> None:
        self._output = output
        self.requests: list[RoutineRuleGenerationRequest] = []

    async def generate(self, request: RoutineRuleGenerationRequest) -> RoutineRuleModelOutput:
        self.requests.append(request)
        return self._output.model_copy(deep=True)


class FixedRoutineDraftGenerator(RoutineDraftGenerator):
    def __init__(self, output: RoutineDraftModelOutput) -> None:
        self._output = output
        self.requests: list[RoutineDraftGenerationRequest] = []

    async def generate(self, request: RoutineDraftGenerationRequest) -> RoutineDraftModelOutput:
        self.requests.append(request)
        return self._output.model_copy(deep=True)


class RoutinePlannerHarness:
    RETINOL_ID = "product:retinol-serum"
    DIRECTIONS_SOURCE_ID = "product-directions:product:retinol-serum:v1"

    def product(self, directions: str | None = "저녁에만 사용하세요.") -> ProductRecord:
        return ProductRecord(
            product_id=self.RETINOL_ID,
            version="v1",
            name="테스트 레티놀 세럼",
            ingredient_ids=["ingredient:retinol"],
            directions=directions,
            source_id="test-products",
            checked_at="2026-09-21",
            is_demo=False,
        )

    def rule(
        self,
        *,
        source_id: str | None = None,
        source_quote: str = "저녁에만 사용",
    ) -> RoutineRuleCandidate:
        return RoutineRuleCandidate(
            rule_type=RoutineRuleType.ALLOWED_PERIOD,
            product_ids=[self.RETINOL_ID],
            source_id=source_id or self.DIRECTIONS_SOURCE_ID,
            source_quote=source_quote,
            rationale="레티놀 제품은 저녁에만 배치",
            allowed_periods=[DayPeriod.EVENING],
        )

    def draft(
        self,
        *,
        product_id: str | None = None,
        period: DayPeriod = DayPeriod.EVENING,
    ) -> RoutineDraftModelOutput:
        effective_product_id = product_id or self.RETINOL_ID
        return RoutineDraftModelOutput(
            placements=[
                RoutineDraftPlacement(
                    product_id=effective_product_id,
                    weekday=weekday,
                    period=period,
                    order=1,
                    reason="검증된 Rule에 따른 테스트 배치",
                )
                for weekday in (Weekday.MONDAY, Weekday.TUESDAY)
            ]
        )

    def request(
        self,
        product: ProductRecord,
        evidence: list[EvidenceRecord] | None = None,
        case_usage_guidance: list[CaseUsageGuidance] | None = None,
    ) -> RoutinePlanRequest:
        return RoutinePlanRequest(
            chat_room_id="routine-room",
            request_id="routine-request",
            products=[product],
            user_request="레티놀 제품으로 저녁 루틴을 짜줘",
            evidence_records=evidence or [],
            case_usage_guidance=case_usage_guidance or [],
        )

    def evidence(self) -> EvidenceRecord:
        return EvidenceRecord(
            source_type=EvidenceSourceType.PAPER,
            text_kind=EvidenceTextKind.EXCERPT,
            evidence_id="evidence-1",
            source_id="pubmed-1",
            source_title="테스트 Evidence",
            text="레티놀 제품은 저녁에 사용합니다.",
            locator="abstract:0",
            target_ids=["ingredient:retinol"],
            conditions=EvidenceConditions(usage="저녁 사용"),
            review_status=EvidenceReviewStatus.UNREVIEWED,
            is_demo=False,
        )


class TestSourceBoundRoutinePlanner:
    async def test_제품_사용법_exact_quote_Rule을_강제해_루틴을_확정한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product()
        rule_generator = FixedRoutineRuleGenerator(
            RoutineRuleModelOutput(rules=[harness.rule()])
        )
        draft_generator = FixedRoutineDraftGenerator(harness.draft())
        planner = SourceBoundRoutinePlanner(rule_generator, draft_generator)
        request = harness.request(product)

        plan = await planner.plan(request)
        validation = await planner.validate(
            RoutineValidationRequest(plan=plan, products=[product])
        )

        assert validation.valid is True
        assert validation.violations == []
        assert plan.rules[0].enforcement is RoutineRuleEnforcement.REQUIRED
        assert all(placement.period is DayPeriod.EVENING for placement in plan.placements)
        assert rule_generator.requests[0].sources[0].text == product.directions

    async def test_원문에_없는_quote_Rule은_제외하고_경고를_남긴다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product()
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(
                RoutineRuleModelOutput(
                    rules=[harness.rule(source_quote="원문에 없는 아침 사용 금지")]
                )
            ),
            FixedRoutineDraftGenerator(harness.draft(period=DayPeriod.MORNING)),
        )
        request = harness.request(product)

        plan = await planner.plan(request)
        validation = await planner.validate(
            RoutineValidationRequest(plan=plan, products=[product])
        )

        assert plan.rules == []
        assert any("출처 원문과 일치하지 않는" in warning for warning in validation.warnings)

    async def test_미검수_Evidence_Rule은_강제하지_않고_경고로_내린다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        evidence = harness.evidence()
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(
                RoutineRuleModelOutput(
                    rules=[
                        harness.rule(
                            source_id="evidence:evidence-1",
                            source_quote="저녁에 사용",
                        )
                    ]
                )
            ),
            FixedRoutineDraftGenerator(harness.draft(period=DayPeriod.MORNING)),
        )
        request = harness.request(product, evidence=[evidence])

        plan = await planner.plan(request)
        validation = await planner.validate(
            RoutineValidationRequest(plan=plan, products=[product])
        )

        assert validation.valid is True
        assert plan.rules[0].enforcement is RoutineRuleEnforcement.WARNING
        assert "레티놀 제품은 저녁에만 배치" in validation.warnings

    async def test_Case_사용법은_성분이_겹치는_상품에만_경고로_전달한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        guidance = CaseUsageGuidance(
            source_id="nia-case-usage:CASE-1",
            case_id="CASE-1",
            text="3. 사용법 및 관리방안\n레티놀은 저녁에 사용합니다.",
            ingredient_ids=["ingredient:retinol"],
        )
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(
                RoutineRuleModelOutput(
                    rules=[
                        harness.rule(
                            source_id=guidance.source_id,
                            source_quote="레티놀은 저녁에 사용합니다.",
                        )
                    ]
                )
            ),
            FixedRoutineDraftGenerator(harness.draft(period=DayPeriod.MORNING)),
        )

        plan = await planner.plan(
            harness.request(product, case_usage_guidance=[guidance])
        )
        validation = await planner.validate(
            RoutineValidationRequest(plan=plan, products=[product])
        )

        assert validation.valid is True
        assert plan.rules[0].source_kind is RoutineRuleSourceKind.CASE_USAGE_GUIDANCE
        assert plan.rules[0].enforcement is RoutineRuleEnforcement.WARNING
        assert plan.constraints[0].source is ConstraintSource.CASE_USAGE_GUIDANCE
        assert "레티놀 제품은 저녁에만 배치" in validation.warnings

    async def test_LLM이_입력에_없는_제품을_배치하면_확정하지_않는다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(RoutineRuleModelOutput()),
            FixedRoutineDraftGenerator(harness.draft(product_id="product:unknown")),
        )
        request = harness.request(product)

        plan = await planner.plan(request)
        validation = await planner.validate(
            RoutineValidationRequest(plan=plan, products=[product])
        )

        assert validation.valid is False
        assert any("허용되지 않은 제품 ID" in item for item in validation.violations)
        assert any("선택한 제품이 루틴에서 누락" in item for item in validation.violations)
