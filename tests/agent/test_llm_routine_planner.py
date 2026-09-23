"""LLM Rule 후보와 루틴 초안의 결정적 방어 계층 검증."""

import json

import pytest

from agent.ports import RoutineDraftGenerator, RoutineRuleGenerator
from agent.rag.routine_planner import (
    RoutineFrequencyInterpreter,
    RoutineRuleGenerationError,
    RoutineRuleGenerationFailureKind,
    SourceBoundRoutinePlanner,
)
from agent.rag.schemas import (
    AllowedPeriodRoutineRuleCandidate,
    CaseUsageGuidance,
    ConstraintSource,
    DayPeriod,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSourceType,
    EvidenceTextKind,
    MaxFrequencyRoutineRuleCandidate,
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
    RoutineScheduleConstraints,
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


class FailingRoutineRuleGenerator(RoutineRuleGenerator):
    def __init__(self, failure_kind: RoutineRuleGenerationFailureKind) -> None:
        self._failure_kind = failure_kind

    async def generate(self, request: RoutineRuleGenerationRequest) -> RoutineRuleModelOutput:
        raise RoutineRuleGenerationError(
            failure_kind=self._failure_kind,
            source_kinds=[source.source_kind for source in request.sources],
            detail="테스트 구조화 출력 실패",
        )


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
        return AllowedPeriodRoutineRuleCandidate(
            rule_type=RoutineRuleType.ALLOWED_PERIOD,
            product_ids=[self.RETINOL_ID],
            source_id=source_id or self.DIRECTIONS_SOURCE_ID,
            source_quote=source_quote,
            rationale="레티놀 제품은 저녁에만 배치",
            allowed_periods=[DayPeriod.EVENING],
        )

    def frequency_rule(
        self,
        *,
        source_id: str,
        source_quote: str,
        max_frequency_per_week: int | None,
    ) -> MaxFrequencyRoutineRuleCandidate:
        return MaxFrequencyRoutineRuleCandidate(
            rule_type=RoutineRuleType.MAX_FREQUENCY_PER_WEEK,
            product_ids=[self.RETINOL_ID],
            source_id=source_id,
            source_quote=source_quote,
            rationale="레티놀 제품의 주당 사용 일수 제한",
            max_frequency_per_week=max_frequency_per_week,
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
        schedule: RoutineScheduleConstraints | None = None,
    ) -> RoutinePlanRequest:
        return RoutinePlanRequest(
            chat_room_id="routine-room",
            request_id="routine-request",
            products=[product],
            user_request="레티놀 제품으로 저녁 루틴을 짜줘",
            schedule=schedule or RoutineScheduleConstraints(),
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

    def guidance(self, text: str) -> CaseUsageGuidance:
        return CaseUsageGuidance(
            source_id="nia-case-usage:CASE-1",
            case_id="CASE-1",
            text=text,
            ingredient_ids=["ingredient:retinol"],
        )


class TestRoutineRuleContract:
    def test_OpenAI_지원_Schema로_Rule_타입별_필수값을_분리한다(self) -> None:
        schema = RoutineRuleModelOutput.model_json_schema()
        serialized = json.dumps(schema)
        max_frequency_schema = schema["$defs"]["MaxFrequencyRoutineRuleCandidate"]

        assert "anyOf" in serialized
        assert "oneOf" not in serialized
        assert "discriminator" not in serialized
        assert "const" not in serialized
        frequency_schema = max_frequency_schema["properties"]["max_frequency_per_week"]
        assert {item.get("type") for item in frequency_schema["anyOf"]} == {"integer", "null"}

    def test_주당_횟수가_null인_후보도_다른_Rule과_함께_파싱한다(self) -> None:
        output = RoutineRuleModelOutput.model_validate(
            {
                "rules": [
                    {
                        "rule_type": RoutineRuleType.ALLOWED_PERIOD.value,
                        "product_ids": [RoutinePlannerHarness.RETINOL_ID],
                        "source_id": RoutinePlannerHarness.DIRECTIONS_SOURCE_ID,
                        "source_quote": "저녁에만 사용",
                        "rationale": "레티놀 제품은 저녁에만 배치",
                        "allowed_periods": [DayPeriod.EVENING.value],
                        "max_frequency_per_week": None,
                        "related_product_ids": [],
                    },
                    {
                        "rule_type": RoutineRuleType.MAX_FREQUENCY_PER_WEEK.value,
                        "product_ids": [RoutinePlannerHarness.RETINOL_ID],
                        "source_id": RoutinePlannerHarness.DIRECTIONS_SOURCE_ID,
                        "source_quote": "아침저녁으로 사용",
                        "rationale": "레티놀 제품의 사용 빈도 제한",
                        "allowed_periods": [],
                        "max_frequency_per_week": None,
                        "related_product_ids": [],
                    },
                ]
            }
        )

        assert len(output.rules) == 2
        assert output.rules[1].max_frequency_per_week is None


class TestRoutineFrequencyInterpreter:
    def test_3일간_루틴은_주당_횟수가_아닌_기간으로_해석한다(self) -> None:
        schedule = RoutineFrequencyInterpreter().schedule("추천 상품으로 3일간 루틴")

        assert schedule.duration_days == 3
        assert schedule.applications_per_week is None

    def test_단독_횟수는_주당_횟수로_해석한다(self) -> None:
        interpreter = RoutineFrequencyInterpreter()

        assert interpreter.grounded_source_frequencies("처음에는 3회 사용합니다.") == {3}
        schedule = interpreter.schedule("이 제품으로 4회 루틴 짜줘")
        assert schedule.duration_days is None
        assert schedule.applications_per_week == 4

    @pytest.mark.parametrize("text", ["하루 2회 사용", "매일 2번 사용", "아침저녁 2회 사용"])
    def test_일일_표현은_주당_횟수로_해석하지_않는다(self, text: str) -> None:
        assert RoutineFrequencyInterpreter().grounded_source_frequencies(text) == set()
        assert RoutineFrequencyInterpreter().schedule(text).applications_per_week is None

    def test_아침과_저녁은_시간대로만_보존한다(self) -> None:
        schedule = RoutineFrequencyInterpreter().schedule("아침저녁 3일간 루틴")

        assert schedule.periods == [DayPeriod.MORNING, DayPeriod.EVENING]
        assert schedule.duration_days == 3
        assert schedule.applications_per_week is None


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

    async def test_document_status와_무관하게_Evidence_Rule을_강제한다(self) -> None:
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
            FixedRoutineDraftGenerator(harness.draft(period=DayPeriod.EVENING)),
        )
        request = harness.request(product, evidence=[evidence])

        plan = await planner.plan(request)
        validation = await planner.validate(
            RoutineValidationRequest(plan=plan, products=[product])
        )

        assert validation.valid is True
        assert validation.violations == []
        assert plan.rules[0].enforcement is RoutineRuleEnforcement.REQUIRED

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

    async def test_기간은_아침저녁_배치가_아니라_서로_다른_요일_수로_검증한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        draft = RoutineDraftModelOutput(
            placements=[
                RoutineDraftPlacement(
                    product_id=product.product_id,
                    weekday=Weekday.MONDAY,
                    period=period,
                    order=1,
                    reason="같은 날의 아침저녁 배치",
                )
                for period in (DayPeriod.MORNING, DayPeriod.EVENING)
            ]
        )
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(RoutineRuleModelOutput()),
            FixedRoutineDraftGenerator(draft),
        )
        schedule = RoutineScheduleConstraints(
            duration_days=1,
            periods=[DayPeriod.MORNING, DayPeriod.EVENING],
        )

        plan = await planner.plan(harness.request(product, schedule=schedule))
        validation = await planner.validate(
            RoutineValidationRequest(
                plan=plan,
                products=[product],
                schedule=schedule,
            )
        )

        assert validation.valid is True

    async def test_주당_횟수는_같은_날의_아침저녁도_각각_계산한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        draft = RoutineDraftModelOutput(
            placements=[
                RoutineDraftPlacement(
                    product_id=product.product_id,
                    weekday=Weekday.MONDAY,
                    period=period,
                    order=1,
                    reason="같은 날의 아침저녁 배치",
                )
                for period in (DayPeriod.MORNING, DayPeriod.EVENING)
            ]
        )
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(RoutineRuleModelOutput()),
            FixedRoutineDraftGenerator(draft),
        )
        schedule = RoutineScheduleConstraints(applications_per_week=1)

        plan = await planner.plan(harness.request(product, schedule=schedule))
        validation = await planner.validate(
            RoutineValidationRequest(
                plan=plan,
                products=[product],
                schedule=schedule,
            )
        )

        assert validation.valid is False
        assert any("주당 횟수" in item for item in validation.violations)

    async def test_출처의_최대_횟수도_실제_배치_횟수로_검증한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions="주 1회 사용")
        draft = RoutineDraftModelOutput(
            placements=[
                RoutineDraftPlacement(
                    product_id=product.product_id,
                    weekday=Weekday.MONDAY,
                    period=period,
                    order=1,
                    reason="같은 날의 아침저녁 배치",
                )
                for period in (DayPeriod.MORNING, DayPeriod.EVENING)
            ]
        )
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(
                RoutineRuleModelOutput(
                    rules=[
                        harness.frequency_rule(
                            source_id=harness.DIRECTIONS_SOURCE_ID,
                            source_quote="주 1회",
                            max_frequency_per_week=1,
                        )
                    ]
                )
            ),
            FixedRoutineDraftGenerator(draft),
        )

        plan = await planner.plan(harness.request(product))
        validation = await planner.validate(
            RoutineValidationRequest(plan=plan, products=[product])
        )

        assert validation.valid is False
        assert any("최대 사용 빈도" in item for item in validation.violations)

    async def test_일일_빈도를_주당_횟수로_만든_Rule만_제외한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        guidance = harness.guidance(
            "3. 사용법 및 관리방안\n"
            "아침저녁으로 사용하고 레티놀은 저녁에 사용합니다."
        )
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(
                RoutineRuleModelOutput(
                    rules=[
                        harness.frequency_rule(
                            source_id=guidance.source_id,
                            source_quote="아침저녁으로 사용",
                            max_frequency_per_week=2,
                        ),
                        harness.rule(
                            source_id=guidance.source_id,
                            source_quote="레티놀은 저녁에 사용합니다.",
                        ),
                    ]
                )
            ),
            FixedRoutineDraftGenerator(harness.draft()),
        )

        plan = await planner.plan(
            harness.request(product, case_usage_guidance=[guidance])
        )

        assert len(plan.rules) == 1
        assert plan.rules[0].rule_type is RoutineRuleType.ALLOWED_PERIOD
        assert any("같은 주당 횟수가 명시되지 않은" in warning for warning in plan.warnings)

    async def test_주당_횟수가_없는_후보만_제외하고_나머지_Rule은_유지한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        guidance = harness.guidance(
            "3. 사용법 및 관리방안\n아침저녁으로 사용하고 레티놀은 저녁에 사용합니다."
        )
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(
                RoutineRuleModelOutput(
                    rules=[
                        harness.frequency_rule(
                            source_id=guidance.source_id,
                            source_quote="아침저녁으로 사용",
                            max_frequency_per_week=None,
                        ),
                        harness.rule(
                            source_id=guidance.source_id,
                            source_quote="레티놀은 저녁에 사용합니다.",
                        ),
                    ]
                )
            ),
            FixedRoutineDraftGenerator(harness.draft()),
        )

        plan = await planner.plan(harness.request(product, case_usage_guidance=[guidance]))

        assert len(plan.rules) == 1
        assert plan.rules[0].rule_type is RoutineRuleType.ALLOWED_PERIOD
        assert any("주당 횟수가 없는" in warning for warning in plan.warnings)

    async def test_원문과_일치하는_명시적_주당_횟수_Rule은_유지한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        guidance = harness.guidance(
            "3. 사용법 및 관리방안\n레티놀 제품은 주 2회 저녁에 사용합니다."
        )
        planner = SourceBoundRoutinePlanner(
            FixedRoutineRuleGenerator(
                RoutineRuleModelOutput(
                    rules=[
                        harness.frequency_rule(
                            source_id=guidance.source_id,
                            source_quote="주 2회",
                            max_frequency_per_week=2,
                        )
                    ]
                )
            ),
            FixedRoutineDraftGenerator(harness.draft()),
        )

        plan = await planner.plan(
            harness.request(product, case_usage_guidance=[guidance])
        )

        assert len(plan.rules) == 1
        assert plan.rules[0].max_frequency_per_week == 2
        assert plan.warnings == []

    async def test_Case_Rule_구조화_실패는_경고로_격리한다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        guidance = harness.guidance(
            "3. 사용법 및 관리방안\n레티놀은 저녁에 사용합니다."
        )
        draft_generator = FixedRoutineDraftGenerator(harness.draft())
        planner = SourceBoundRoutinePlanner(
            FailingRoutineRuleGenerator(
                RoutineRuleGenerationFailureKind.STRUCTURED_OUTPUT
            ),
            draft_generator,
        )

        plan = await planner.plan(
            harness.request(product, case_usage_guidance=[guidance])
        )

        assert plan.rules == []
        assert any("구조화하지 못해" in warning for warning in plan.warnings)
        assert draft_generator.requests[0].rules == []

    async def test_제품_공식_사용법_Rule_구조화_실패는_숨기지_않는다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product()
        planner = SourceBoundRoutinePlanner(
            FailingRoutineRuleGenerator(
                RoutineRuleGenerationFailureKind.STRUCTURED_OUTPUT
            ),
            FixedRoutineDraftGenerator(harness.draft()),
        )

        with pytest.raises(RoutineRuleGenerationError):
            await planner.plan(harness.request(product))

    async def test_Case_Rule_모델_호출_실패는_숨기지_않는다(self) -> None:
        harness = RoutinePlannerHarness()
        product = harness.product(directions=None)
        guidance = harness.guidance(
            "3. 사용법 및 관리방안\n레티놀은 저녁에 사용합니다."
        )
        planner = SourceBoundRoutinePlanner(
            FailingRoutineRuleGenerator(
                RoutineRuleGenerationFailureKind.MODEL_INVOCATION
            ),
            FixedRoutineDraftGenerator(harness.draft()),
        )

        with pytest.raises(RoutineRuleGenerationError):
            await planner.plan(
                harness.request(product, case_usage_guidance=[guidance])
            )
