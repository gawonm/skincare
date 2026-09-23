"""검증된 Rule과 서비스 역할 순서만으로 루틴 배치를 계산한다."""

from collections import defaultdict
from typing import ClassVar

from agent.rag.routine_product_selector import RoutineProductSelector
from agent.rag.schemas import (
    DEFAULT_ROUTINE_DURATION_DAYS,
    DayPeriod,
    DeterministicRoutineScheduleRequest,
    DeterministicRoutineScheduleResult,
    ProductRecord,
    RoutinePlacement,
    RoutineProductRole,
    RoutineRule,
    RoutineRuleEnforcement,
    RoutineRuleSourceKind,
    RoutineRuleType,
    Weekday,
)


class DeterministicRoutineScheduler:
    """LLM이 만든 문장 대신 검증된 구조화 Rule로 일정과 순서를 결정한다."""

    _WEEKDAY_ORDER: ClassVar[tuple[Weekday, ...]] = (
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
        Weekday.THURSDAY,
        Weekday.FRIDAY,
        Weekday.SATURDAY,
        Weekday.SUNDAY,
    )
    _PERIOD_ORDER: ClassVar[tuple[DayPeriod, ...]] = (
        DayPeriod.MORNING,
        DayPeriod.EVENING,
        DayPeriod.UNSPECIFIED,
    )
    _ROLE_ORDER: ClassVar[dict[RoutineProductRole, int]] = {
        RoutineProductRole.CLEANSE: 0,
        RoutineProductRole.CARE: 1,
        RoutineProductRole.SPECIAL_CARE: 2,
        RoutineProductRole.MOISTURIZE: 3,
        RoutineProductRole.UNCLASSIFIED: 4,
    }
    _ROLE_REASON: ClassVar[dict[RoutineProductRole, str]] = {
        RoutineProductRole.CLEANSE: "세안 역할 대표 상품",
        RoutineProductRole.CARE: "케어 역할 대표 상품",
        RoutineProductRole.SPECIAL_CARE: "검증된 사용 Rule이 있는 특별 케어 상품을 1회 배치",
        RoutineProductRole.MOISTURIZE: "보습 역할 대표 상품",
        RoutineProductRole.UNCLASSIFIED: "미분류 상품",
    }
    _SPECIAL_RULE_SOURCES: ClassVar[frozenset[RoutineRuleSourceKind]] = frozenset(
        {
            RoutineRuleSourceKind.PRODUCT_DIRECTIONS,
            RoutineRuleSourceKind.EVIDENCE,
            RoutineRuleSourceKind.VERIFIED_EVIDENCE,
        }
    )

    def __init__(self, product_selector: RoutineProductSelector | None = None) -> None:
        self._product_selector = product_selector or RoutineProductSelector()

    def schedule(
        self,
        request: DeterministicRoutineScheduleRequest,
    ) -> DeterministicRoutineScheduleResult:
        available_days = [
            weekday for weekday in self._WEEKDAY_ORDER if weekday not in request.excluded_weekdays
        ]
        selected_days = available_days[: self._sequence_count(request)]
        base_products = [
            product
            for product in request.products
            if self._product_selector.role(product) in RoutineProductSelector.APPLICATION_ROLE_ORDER
        ]
        special_product = next(
            (
                product
                for product in request.products
                if self._product_selector.role(product) is RoutineProductRole.UNCLASSIFIED
                and self._is_special_care_eligible(product, request.rules)
            ),
            None,
        )
        placements: list[RoutinePlacement] = []
        placement_counts: defaultdict[str, int] = defaultdict(int)
        special_scheduled = False

        for weekday in selected_days:
            products_by_period: defaultdict[DayPeriod, list[ProductRecord]] = defaultdict(list)
            for product in base_products:
                for period in self._periods(product, request):
                    if not self._can_repeat(product, placement_counts, request):
                        break
                    products_by_period[period].append(product)
                    placement_counts[product.product_id] += 1

            if special_product is not None and not special_scheduled:
                for period in self._periods(special_product, request)[:1]:
                    if self._has_same_period_conflict(
                        special_product,
                        products_by_period[period],
                        request.rules,
                    ):
                        continue
                    products_by_period[period].append(special_product)
                    placement_counts[special_product.product_id] += 1
                    special_scheduled = True
                    break

            for period in self._PERIOD_ORDER:
                slot_products = products_by_period.get(period, [])
                for order, product in enumerate(
                    self._ordered_products(slot_products, request.rules),
                    start=1,
                ):
                    role = self._placement_role(product, special_product)
                    placements.append(
                        RoutinePlacement(
                            weekday=weekday,
                            period=period,
                            product_id=product.product_id,
                            product_name=product.name,
                            order=order,
                            reason=self._ROLE_REASON[role],
                        )
                    )

        return DeterministicRoutineScheduleResult(placements=placements)

    def _sequence_count(self, request: DeterministicRoutineScheduleRequest) -> int:
        return (
            request.schedule.duration_days
            or request.schedule.occurrence_count
            or request.schedule.applications_per_week
            or DEFAULT_ROUTINE_DURATION_DAYS
        )

    def _periods(
        self,
        product: ProductRecord,
        request: DeterministicRoutineScheduleRequest,
    ) -> list[DayPeriod]:
        allowed = self._allowed_periods(product.product_id, request.rules)
        if request.schedule.periods:
            if allowed is None:
                return list(request.schedule.periods)
            return [period for period in request.schedule.periods if period in allowed]
        if allowed is not None:
            return allowed[:1]
        return [DayPeriod.UNSPECIFIED]

    def _allowed_periods(
        self,
        product_id: str,
        rules: list[RoutineRule],
    ) -> list[DayPeriod] | None:
        allowed: set[DayPeriod] | None = None
        for rule in rules:
            if (
                rule.enforcement is RoutineRuleEnforcement.REQUIRED
                and rule.rule_type is RoutineRuleType.ALLOWED_PERIOD
                and product_id in rule.product_ids
            ):
                rule_periods = set(rule.allowed_periods)
                allowed = rule_periods if allowed is None else allowed.intersection(rule_periods)
        if allowed is None:
            return None
        return [period for period in self._PERIOD_ORDER if period in allowed]

    def _can_repeat(
        self,
        product: ProductRecord,
        placement_counts: defaultdict[str, int],
        request: DeterministicRoutineScheduleRequest,
    ) -> bool:
        limits = [
            rule.max_frequency_per_week
            for rule in request.rules
            if (
                rule.enforcement is RoutineRuleEnforcement.REQUIRED
                and rule.rule_type is RoutineRuleType.MAX_FREQUENCY_PER_WEEK
                and product.product_id in rule.product_ids
                and rule.max_frequency_per_week is not None
            )
        ]
        if request.schedule.applications_per_week is not None:
            limits.append(request.schedule.applications_per_week)
        return not limits or placement_counts[product.product_id] < min(limits)

    def _is_special_care_eligible(
        self,
        product: ProductRecord,
        rules: list[RoutineRule],
    ) -> bool:
        return any(
            rule.enforcement is RoutineRuleEnforcement.REQUIRED
            and rule.source_kind in self._SPECIAL_RULE_SOURCES
            and rule.rule_type is not RoutineRuleType.WARNING
            and product.product_id in rule.product_ids
            for rule in rules
        )

    def _has_same_period_conflict(
        self,
        candidate: ProductRecord,
        placed_products: list[ProductRecord],
        rules: list[RoutineRule],
    ) -> bool:
        placed_ids = {product.product_id for product in placed_products}
        for rule in rules:
            if (
                rule.enforcement is not RoutineRuleEnforcement.REQUIRED
                or rule.rule_type is not RoutineRuleType.AVOID_SAME_PERIOD
            ):
                continue
            if (
                candidate.product_id in rule.product_ids
                and placed_ids.intersection(rule.related_product_ids)
            ) or (
                candidate.product_id in rule.related_product_ids
                and placed_ids.intersection(rule.product_ids)
            ):
                return True
        return False

    def _ordered_products(
        self,
        products: list[ProductRecord],
        rules: list[RoutineRule],
    ) -> list[ProductRecord]:
        unique = {product.product_id: product for product in products}
        original_order = {product.product_id: index for index, product in enumerate(products)}
        edges: defaultdict[str, set[str]] = defaultdict(set)
        incoming: defaultdict[str, int] = defaultdict(int)
        for rule in rules:
            if (
                rule.enforcement is not RoutineRuleEnforcement.REQUIRED
                or rule.rule_type is not RoutineRuleType.ORDER_BEFORE
            ):
                continue
            for product_id in rule.product_ids:
                for related_id in rule.related_product_ids:
                    if (
                        product_id not in unique
                        or related_id not in unique
                        or related_id in edges[product_id]
                    ):
                        continue
                    edges[product_id].add(related_id)
                    incoming[related_id] += 1

        ordered_ids: list[str] = []
        remaining = set(unique)
        while remaining:
            available = [product_id for product_id in remaining if incoming[product_id] == 0]
            if not available:
                # 순환 Rule은 검증기에서 충돌로 드러내고, 출력 자체는 서비스 순서로 안정화한다.
                available = list(remaining)
            next_id = min(
                available,
                key=lambda product_id: (
                    self._ROLE_ORDER[self._ordered_role(unique[product_id], rules)],
                    original_order[product_id],
                ),
            )
            ordered_ids.append(next_id)
            remaining.remove(next_id)
            for related_id in edges[next_id]:
                incoming[related_id] -= 1
        return [unique[product_id] for product_id in ordered_ids]

    def _placement_role(
        self,
        product: ProductRecord,
        special_product: ProductRecord | None,
    ) -> RoutineProductRole:
        if special_product is not None and product.product_id == special_product.product_id:
            return RoutineProductRole.SPECIAL_CARE
        return self._product_selector.role(product)

    def _ordered_role(
        self,
        product: ProductRecord,
        rules: list[RoutineRule],
    ) -> RoutineProductRole:
        role = self._product_selector.role(product)
        if role is RoutineProductRole.UNCLASSIFIED and self._is_special_care_eligible(
            product, rules
        ):
            return RoutineProductRole.SPECIAL_CARE
        return role
