"""역할·검증 Rule 기반 결정론적 루틴 스케줄러의 핵심 정책을 검증한다."""

from agent.rag.deterministic_routine_scheduler import DeterministicRoutineScheduler
from agent.rag.schemas import (
    DayPeriod,
    DeterministicRoutineScheduleRequest,
    ProductCategory,
    ProductRecord,
    RoutineRule,
    RoutineRuleEnforcement,
    RoutineRuleSourceKind,
    RoutineRuleType,
    RoutineScheduleConstraints,
    Weekday,
)


class DeterministicRoutineSchedulerFixture:
    def product(
        self,
        product_id: str,
        category: str,
        directions: str | None = None,
    ) -> ProductRecord:
        return ProductRecord(
            product_id=product_id,
            name=product_id,
            category=ProductCategory(code=category, name=category),
            directions=directions,
            source_id=f"source:{product_id}",
            checked_at="2026-09-23T00:00:00Z",
            is_demo=False,
        )

    def rule(
        self,
        product_id: str,
        rule_type: RoutineRuleType,
        *,
        allowed_periods: list[DayPeriod] | None = None,
        max_frequency_per_week: int | None = None,
        related_product_ids: list[str] | None = None,
        source_kind: RoutineRuleSourceKind = RoutineRuleSourceKind.PRODUCT_DIRECTIONS,
    ) -> RoutineRule:
        return RoutineRule(
            rule_type=rule_type,
            product_ids=[product_id],
            source_id=f"product-directions:{product_id}:v1",
            source_quote="공식 사용법",
            rationale="테스트용 검증 Rule",
            allowed_periods=allowed_periods or [],
            max_frequency_per_week=max_frequency_per_week,
            related_product_ids=related_product_ids or [],
            source_kind=source_kind,
            enforcement=RoutineRuleEnforcement.REQUIRED,
        )


class TestDeterministicRoutineScheduler:
    def test_기본_역할을_세안_케어_보습_순서로_3일간_반복한다(self) -> None:
        fixture = DeterministicRoutineSchedulerFixture()
        products = [
            fixture.product("cream", "크림·로션"),
            fixture.product("cleanser", "클렌저"),
            fixture.product("serum", "에센스·세럼"),
        ]

        result = DeterministicRoutineScheduler().schedule(
            DeterministicRoutineScheduleRequest(
                products=products,
                schedule=RoutineScheduleConstraints(duration_days=3),
            )
        )

        assert len(result.placements) == 9
        assert {placement.period for placement in result.placements} == {DayPeriod.UNSPECIFIED}
        for weekday in (Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY):
            assert [
                placement.product_id
                for placement in result.placements
                if placement.weekday is weekday
            ] == ["cleanser", "serum", "cream"]

    def test_미분류_상품은_검증된_Rule이_있을_때만_특별케어로_한_번_배치한다(self) -> None:
        fixture = DeterministicRoutineSchedulerFixture()
        cleanser = fixture.product("cleanser", "클렌저")
        serum = fixture.product("serum", "에센스·세럼")
        cream = fixture.product("cream", "크림·로션")
        booster = fixture.product("booster", "기타", directions="공식 사용법")
        rule = fixture.rule(
            booster.product_id,
            RoutineRuleType.ALLOWED_PERIOD,
            allowed_periods=[DayPeriod.EVENING],
        )

        result = DeterministicRoutineScheduler().schedule(
            DeterministicRoutineScheduleRequest(
                products=[cleanser, serum, cream, booster],
                schedule=RoutineScheduleConstraints(
                    duration_days=3,
                    periods=[DayPeriod.EVENING],
                ),
                rules=[rule],
            )
        )

        assert [
            placement.product_id
            for placement in result.placements
            if placement.weekday is Weekday.MONDAY
        ] == ["cleanser", "serum", "booster", "cream"]
        assert (
            sum(placement.product_id == booster.product_id for placement in result.placements) == 1
        )

    def test_Rule이_없는_미분류_상품은_일정에_넣지_않는다(self) -> None:
        fixture = DeterministicRoutineSchedulerFixture()
        booster = fixture.product("booster", "기타", directions="사용법 문장")

        result = DeterministicRoutineScheduler().schedule(
            DeterministicRoutineScheduleRequest(
                products=[booster],
                schedule=RoutineScheduleConstraints(occurrence_count=3),
            )
        )

        assert result.placements == []

    def test_공식_사용법이_없어도_검수된_Evidence_Rule이면_특별케어로_배치한다(
        self,
    ) -> None:
        fixture = DeterministicRoutineSchedulerFixture()
        booster = fixture.product("booster", "기타")
        rule = fixture.rule(
            booster.product_id,
            RoutineRuleType.ALLOWED_PERIOD,
            allowed_periods=[DayPeriod.EVENING],
            source_kind=RoutineRuleSourceKind.VERIFIED_EVIDENCE,
        )

        result = DeterministicRoutineScheduler().schedule(
            DeterministicRoutineScheduleRequest(
                products=[booster],
                schedule=RoutineScheduleConstraints(occurrence_count=3),
                rules=[rule],
            )
        )

        assert len(result.placements) == 1
        assert result.placements[0].period is DayPeriod.EVENING

    def test_검증된_최대_빈도는_기본_역할의_반복보다_우선한다(self) -> None:
        fixture = DeterministicRoutineSchedulerFixture()
        serum = fixture.product("serum", "에센스·세럼")
        rule = fixture.rule(
            serum.product_id,
            RoutineRuleType.MAX_FREQUENCY_PER_WEEK,
            max_frequency_per_week=1,
        )

        result = DeterministicRoutineScheduler().schedule(
            DeterministicRoutineScheduleRequest(
                products=[serum],
                schedule=RoutineScheduleConstraints(duration_days=3),
                rules=[rule],
            )
        )

        assert len(result.placements) == 1

    def test_검증된_순서_Rule은_서비스_역할_순서보다_우선한다(self) -> None:
        fixture = DeterministicRoutineSchedulerFixture()
        serum = fixture.product("serum", "에센스·세럼")
        cream = fixture.product("cream", "크림·로션")
        rule = fixture.rule(
            cream.product_id,
            RoutineRuleType.ORDER_BEFORE,
            related_product_ids=[serum.product_id],
        )

        result = DeterministicRoutineScheduler().schedule(
            DeterministicRoutineScheduleRequest(
                products=[serum, cream],
                schedule=RoutineScheduleConstraints(duration_days=1),
                rules=[rule],
            )
        )

        assert [placement.product_id for placement in result.placements] == [
            "cream",
            "serum",
        ]
