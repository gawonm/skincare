"""출처 기반 LLM Rule 생성과 결정적 검증을 결합한 루틴 Planner."""

from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

from httpx import HTTPError
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import ValidationError

from agent.ports import RoutineDraftGenerator, RoutinePlanner, RoutineRuleGenerator
from agent.prompts import PromptCatalog, PromptPurpose, PromptRequest
from agent.rag.schemas import (
    ChatModelConfig,
    ConstraintSource,
    DayPeriod,
    EvidenceReviewStatus,
    LlmProvider,
    ProductRecord,
    RoutineConstraint,
    RoutineDraftGenerationRequest,
    RoutineDraftModelOutput,
    RoutinePlacement,
    RoutinePlan,
    RoutinePlanRequest,
    RoutineRule,
    RoutineRuleCandidate,
    RoutineRuleCompilationRequest,
    RoutineRuleCompilationResult,
    RoutineRuleEnforcement,
    RoutineRuleGenerationRequest,
    RoutineRuleModelOutput,
    RoutineRuleSource,
    RoutineRuleSourceKind,
    RoutineRuleType,
    RoutineValidationRequest,
    RoutineValidationResult,
    Weekday,
)


class RoutineChatModelFactory:
    """루틴용 구조화 출력 모델이 채팅 설정을 동일하게 사용하도록 조립한다."""

    def create(self, config: ChatModelConfig) -> ChatOpenAI:
        if config.provider is LlmProvider.OPENAI:
            if config.openai is None:
                raise ValueError("OpenAI 채팅 설정이 없습니다.")
            return ChatOpenAI(
                api_key=config.openai.api_key.get_secret_value(),
                model=config.openai.model.value,
                timeout=config.openai.timeout_seconds,
                max_retries=config.openai.max_retries,
            )
        return ChatOpenAI(
            base_url=config.local.base_url,
            api_key=config.local.api_key.get_secret_value(),
            model=config.local.model,
            timeout=config.local.timeout_seconds,
            max_retries=config.local.max_retries,
        )


class ChatModelRoutineRuleGenerator(RoutineRuleGenerator):
    """제품 사용법과 Evidence 원문에서 구조화된 Rule 후보만 추출한다."""

    def __init__(
        self,
        config: ChatModelConfig,
        prompt_catalog: PromptCatalog | None = None,
    ) -> None:
        self._prompt_catalog = prompt_catalog or PromptCatalog()
        self._client = RoutineChatModelFactory().create(config).with_structured_output(
            RoutineRuleModelOutput
        )

    async def generate(self, request: RoutineRuleGenerationRequest) -> RoutineRuleModelOutput:
        prompt = self._prompt_catalog.get(
            PromptRequest(purpose=PromptPurpose.ROUTINE_RULE_EXTRACTION)
        )
        try:
            result = await self._client.ainvoke(
                [
                    SystemMessage(content=prompt.system_message),
                    HumanMessage(content=request.model_dump_json()),
                ]
            )
        except (
            HTTPError,
            OpenAIError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            raise RuntimeError(f"루틴 Rule 추출에 실패했습니다: {error}") from error
        if not isinstance(result, RoutineRuleModelOutput):
            raise TypeError("루틴 Rule 생성기가 계약된 구조화 응답을 반환하지 않았습니다.")
        return result


class ChatModelRoutineDraftGenerator(RoutineDraftGenerator):
    """검증된 Rule과 허용 제품만 사용해 루틴 일정 초안을 생성한다."""

    def __init__(
        self,
        config: ChatModelConfig,
        prompt_catalog: PromptCatalog | None = None,
    ) -> None:
        self._prompt_catalog = prompt_catalog or PromptCatalog()
        self._client = RoutineChatModelFactory().create(config).with_structured_output(
            RoutineDraftModelOutput
        )

    async def generate(self, request: RoutineDraftGenerationRequest) -> RoutineDraftModelOutput:
        prompt = self._prompt_catalog.get(
            PromptRequest(purpose=PromptPurpose.ROUTINE_PLANNING)
        )
        try:
            result = await self._client.ainvoke(
                [
                    SystemMessage(content=prompt.system_message),
                    HumanMessage(content=request.model_dump_json()),
                ]
            )
        except (
            HTTPError,
            OpenAIError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            raise RuntimeError(f"루틴 초안 생성에 실패했습니다: {error}") from error
        if not isinstance(result, RoutineDraftModelOutput):
            raise TypeError("루틴 초안 생성기가 계약된 구조화 응답을 반환하지 않았습니다.")
        return result


class RoutineRuleSourceBuilder:
    """Planner가 접근할 수 있는 제품·Evidence·Case 사용법을 제품 범위에 묶는다."""

    def build(self, request: RoutinePlanRequest) -> list[RoutineRuleSource]:
        sources = [
            RoutineRuleSource(
                source_id=self._product_source_id(product),
                source_kind=RoutineRuleSourceKind.PRODUCT_DIRECTIONS,
                text=product.directions,
                applicable_product_ids=[product.product_id],
            )
            for product in request.products
            if product.directions is not None
        ]
        for evidence in request.evidence_records:
            applicable_product_ids = [
                product.product_id
                for product in request.products
                if set(product.ingredient_ids).intersection(evidence.target_ids)
            ]
            if not applicable_product_ids:
                continue
            source_kind = (
                RoutineRuleSourceKind.VERIFIED_EVIDENCE
                if evidence.review_status is EvidenceReviewStatus.VERIFIED
                else RoutineRuleSourceKind.UNREVIEWED_EVIDENCE
            )
            sources.append(
                RoutineRuleSource(
                    source_id=f"evidence:{evidence.evidence_id}",
                    source_kind=source_kind,
                    text=evidence.text,
                    applicable_product_ids=applicable_product_ids,
                )
            )
        for guidance in request.case_usage_guidance:
            applicable_product_ids = [
                product.product_id
                for product in request.products
                if set(product.ingredient_ids).intersection(guidance.ingredient_ids)
            ]
            if not applicable_product_ids:
                continue
            sources.append(
                RoutineRuleSource(
                    source_id=guidance.source_id,
                    source_kind=RoutineRuleSourceKind.CASE_USAGE_GUIDANCE,
                    text=guidance.text,
                    applicable_product_ids=applicable_product_ids,
                )
            )
        return sources

    def _product_source_id(self, product: ProductRecord) -> str:
        version = product.version or "unknown"
        return f"product-directions:{product.product_id}:{version}"


class DeterministicRoutineValidator:
    """LLM Rule의 출처와 최종 일정의 기계적 제약만 판정한다."""

    def compile_rules(
        self,
        request: RoutineRuleCompilationRequest,
    ) -> RoutineRuleCompilationResult:
        sources = {source.source_id: source for source in request.sources}
        allowed_product_ids = {product.product_id for product in request.products}
        rules: list[RoutineRule] = []
        warnings: list[str] = []
        seen: set[str] = set()

        for candidate in request.candidates:
            source = sources.get(candidate.source_id)
            rejection = self._candidate_rejection(
                candidate,
                source,
                allowed_product_ids,
            )
            if rejection is not None:
                warnings.append(rejection)
                continue
            if source is None:
                continue
            enforcement = self._enforcement(candidate, source)
            rule = RoutineRule(
                **candidate.model_dump(),
                source_kind=source.source_kind,
                enforcement=enforcement,
            )
            fingerprint = rule.model_dump_json()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            rules.append(rule)

        return RoutineRuleCompilationResult(
            rules=rules,
            warnings=list(dict.fromkeys(warnings)),
        )

    def validate(self, request: RoutineValidationRequest) -> RoutineValidationResult:
        allowed_products = {product.product_id: product for product in request.products}
        violations: list[str] = []
        warnings = list(request.plan.warnings)
        placements = request.plan.placements

        if not placements:
            violations.append("루틴 배치가 비어 있습니다.")

        placed_product_ids = {placement.product_id for placement in placements}
        for product_id, product in allowed_products.items():
            if product_id not in placed_product_ids:
                violations.append(f"선택한 제품이 루틴에서 누락됐습니다: {product.name}")

        seen_placements: set[tuple[str, Weekday, DayPeriod]] = set()
        orders_by_slot: defaultdict[tuple[Weekday, DayPeriod], list[int]] = defaultdict(list)
        weekdays_by_product: defaultdict[str, set[Weekday]] = defaultdict(set)
        placements_by_slot: defaultdict[
            tuple[Weekday, DayPeriod], list[RoutinePlacement]
        ] = (
            defaultdict(list)
        )
        for placement in placements:
            product = allowed_products.get(placement.product_id)
            if product is None:
                violations.append(f"허용되지 않은 제품 ID가 배치됐습니다: {placement.product_id}")
            elif placement.product_name != product.name:
                violations.append(f"제품 ID와 제품명이 일치하지 않습니다: {placement.product_id}")
            if placement.weekday in request.excluded_weekdays:
                violations.append(f"제외 요일에 제품이 배치됐습니다: {placement.weekday.value}")

            placement_key = (placement.product_id, placement.weekday, placement.period)
            if placement_key in seen_placements:
                violations.append(
                    f"동일 제품이 같은 시간대에 중복 배치됐습니다: {placement.product_name}"
                )
            seen_placements.add(placement_key)
            slot = (placement.weekday, placement.period)
            orders_by_slot[slot].append(placement.order)
            placements_by_slot[slot].append(placement)
            weekdays_by_product[placement.product_id].add(placement.weekday)

        for slot, orders in orders_by_slot.items():
            expected_orders = list(range(1, len(orders) + 1))
            if sorted(orders) != expected_orders:
                violations.append(
                    f"{slot[0].value} {slot[1].value} 사용 순서는 1부터 중복 없이 이어져야 합니다."
                )
        for product_id, weekdays in weekdays_by_product.items():
            if len(weekdays) > request.frequency_per_week:
                product_name = allowed_products.get(product_id)
                label = product_name.name if product_name is not None else product_id
                violations.append(
                    f"요청한 주당 횟수를 초과했습니다: {label} ({len(weekdays)}회)"
                )

        for rule in request.plan.rules:
            if rule.enforcement is RoutineRuleEnforcement.WARNING:
                warnings.append(rule.rationale)
                continue
            self._validate_required_rule(
                rule,
                placements,
                placements_by_slot,
                weekdays_by_product,
                violations,
            )

        return RoutineValidationResult(
            valid=not violations,
            violations=list(dict.fromkeys(violations)),
            warnings=list(dict.fromkeys(warnings)),
        )

    def _candidate_rejection(
        self,
        candidate: RoutineRuleCandidate,
        source: RoutineRuleSource | None,
        allowed_product_ids: set[str],
    ) -> str | None:
        if source is None:
            return f"존재하지 않는 출처를 참조한 루틴 Rule을 제외했습니다: {candidate.source_id}"
        if candidate.source_quote not in source.text:
            return f"출처 원문과 일치하지 않는 루틴 Rule을 제외했습니다: {candidate.source_id}"
        candidate_product_ids = set(candidate.product_ids + candidate.related_product_ids)
        if not candidate_product_ids.issubset(allowed_product_ids):
            return f"허용되지 않은 제품을 참조한 루틴 Rule을 제외했습니다: {candidate.source_id}"
        if not candidate_product_ids.issubset(set(source.applicable_product_ids)):
            return f"출처 적용 범위를 벗어난 루틴 Rule을 제외했습니다: {candidate.source_id}"
        if set(candidate.product_ids).intersection(candidate.related_product_ids):
            return f"동일 제품을 상호 제약으로 사용한 루틴 Rule을 제외했습니다: {candidate.source_id}"
        return None

    def _enforcement(
        self,
        candidate: RoutineRuleCandidate,
        source: RoutineRuleSource,
    ) -> RoutineRuleEnforcement:
        if (
            source.source_kind
            in {
                RoutineRuleSourceKind.UNREVIEWED_EVIDENCE,
                RoutineRuleSourceKind.CASE_USAGE_GUIDANCE,
            }
            or candidate.rule_type is RoutineRuleType.WARNING
        ):
            return RoutineRuleEnforcement.WARNING
        return RoutineRuleEnforcement.REQUIRED

    def _validate_required_rule(
        self,
        rule: RoutineRule,
        placements: list[RoutinePlacement],
        placements_by_slot: defaultdict[
            tuple[Weekday, DayPeriod], list[RoutinePlacement]
        ],
        weekdays_by_product: defaultdict[str, set[Weekday]],
        violations: list[str],
    ) -> None:
        if rule.rule_type is RoutineRuleType.ALLOWED_PERIOD:
            for placement in placements:
                if (
                    placement.product_id in rule.product_ids
                    and placement.period not in rule.allowed_periods
                ):
                    violations.append(
                        f"허용 시간대 규칙을 위반했습니다: {placement.product_name}"
                    )
            return
        if rule.rule_type is RoutineRuleType.MAX_FREQUENCY_PER_WEEK:
            if rule.max_frequency_per_week is None:
                return
            for product_id in rule.product_ids:
                if len(weekdays_by_product[product_id]) > rule.max_frequency_per_week:
                    violations.append(f"제품별 최대 사용 빈도를 초과했습니다: {product_id}")
            return
        if rule.rule_type is RoutineRuleType.AVOID_SAME_PERIOD:
            for slot_placements in placements_by_slot.values():
                slot_ids = {placement.product_id for placement in slot_placements}
                if slot_ids.intersection(rule.product_ids) and slot_ids.intersection(
                    rule.related_product_ids
                ):
                    violations.append("같은 시간대 사용 금지 규칙을 위반했습니다.")
            return
        if rule.rule_type is RoutineRuleType.ORDER_BEFORE:
            for slot_placements in placements_by_slot.values():
                orders = {placement.product_id: placement.order for placement in slot_placements}
                for product_id in rule.product_ids:
                    for related_id in rule.related_product_ids:
                        if (
                            product_id in orders
                            and related_id in orders
                            and orders[product_id] >= orders[related_id]
                        ):
                            violations.append("제품 사용 순서 규칙을 위반했습니다.")


class SourceBoundRoutinePlanner(RoutinePlanner):
    """LLM은 Rule·초안을 제안하고 코드는 출처와 최종 배치를 검증한다."""

    def __init__(
        self,
        rule_generator: RoutineRuleGenerator,
        draft_generator: RoutineDraftGenerator,
        validator: DeterministicRoutineValidator | None = None,
        source_builder: RoutineRuleSourceBuilder | None = None,
    ) -> None:
        self._rule_generator = rule_generator
        self._draft_generator = draft_generator
        self._validator = validator or DeterministicRoutineValidator()
        self._source_builder = source_builder or RoutineRuleSourceBuilder()

    async def plan(self, request: RoutinePlanRequest) -> RoutinePlan:
        sources = self._source_builder.build(request)
        candidates = RoutineRuleModelOutput()
        if sources:
            candidates = await self._rule_generator.generate(
                RoutineRuleGenerationRequest(
                    user_request=request.user_request,
                    products=request.products,
                    sources=sources,
                )
            )
        compilation = self._validator.compile_rules(
            RoutineRuleCompilationRequest(
                products=request.products,
                sources=sources,
                candidates=candidates.rules,
            )
        )
        draft = await self._draft_generator.generate(
            RoutineDraftGenerationRequest(
                user_request=request.user_request,
                products=request.products,
                excluded_weekdays=request.excluded_weekdays,
                frequency_per_week=request.frequency_per_week,
                rules=compilation.rules,
                current_plan=request.current_plan,
            )
        )
        products = {product.product_id: product for product in request.products}
        placements = [
            RoutinePlacement(
                product_id=item.product_id,
                product_name=(
                    products[item.product_id].name
                    if item.product_id in products
                    else item.product_id
                ),
                weekday=item.weekday,
                period=item.period,
                order=item.order,
                reason=item.reason,
            )
            for item in draft.placements
        ]
        routine_id = (
            request.current_plan.routine_id
            if request.current_plan is not None
            else str(uuid5(NAMESPACE_URL, f"routine:{request.chat_room_id}"))
        )
        version = request.current_plan.version + 1 if request.current_plan is not None else 1
        return RoutinePlan(
            routine_id=routine_id,
            version=version,
            placements=placements,
            constraints=self._constraints(compilation.rules, request.excluded_weekdays),
            rules=compilation.rules,
            warnings=compilation.warnings,
            changes=(
                ["사용자 요청과 검증된 Rule을 반영해 루틴 초안을 다시 생성함"]
                if request.current_plan is not None
                else []
            ),
            is_demo=False,
        )

    async def validate(self, request: RoutineValidationRequest) -> RoutineValidationResult:
        return self._validator.validate(request)

    def _constraints(
        self,
        rules: list[RoutineRule],
        excluded_weekdays: list[Weekday],
    ) -> list[RoutineConstraint]:
        constraints = [
            RoutineConstraint(
                description=f"{weekday.value} 제외",
                source=ConstraintSource.USER,
            )
            for weekday in excluded_weekdays
        ]
        for rule in rules:
            if rule.source_kind is RoutineRuleSourceKind.PRODUCT_DIRECTIONS:
                source = ConstraintSource.PRODUCT_DIRECTIONS
            elif rule.source_kind is RoutineRuleSourceKind.CASE_USAGE_GUIDANCE:
                source = ConstraintSource.CASE_USAGE_GUIDANCE
            else:
                source = ConstraintSource.EVIDENCE
            constraints.append(
                RoutineConstraint(
                    description=rule.rationale,
                    source=source,
                    source_id=rule.source_id,
                )
            )
        return constraints


class RoutinePlannerFactory:
    """채팅 모델 설정으로 출처 기반 LLM 루틴 Planner를 조립한다."""

    def create(self, config: ChatModelConfig) -> RoutinePlanner:
        return SourceBoundRoutinePlanner(
            rule_generator=ChatModelRoutineRuleGenerator(config),
            draft_generator=ChatModelRoutineDraftGenerator(config),
        )
