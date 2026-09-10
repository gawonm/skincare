"""외부 서비스 없이 그래프를 실행하기 위한 개발용 어댑터."""

import asyncio
import re
from collections.abc import Sequence
from typing import ClassVar
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from agent.ports import (
    ChatHistoryRepository,
    IngredientRepository,
    LlmClient,
    ProductRepository,
    RoomAccessDeniedError,
    RoomNotFoundError,
    RoutinePlanner,
    TurnStorageError,
)
from agent.rag.ports import EvidenceRetriever
from agent.rag.retrieval.ingredient_mention_resolver import IngredientMentionResolver
from agent.rag.schemas import (
    ConstraintSource,
    DayPeriod,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    EvidenceSourceType,
    IngredientRecord,
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    ProductCandidateSet,
    ProductCategory,
    ProductGetRequest,
    ProductGetResult,
    ProductRecord,
    ProductSearchRequest,
    ProductSearchResult,
    ProductTexture,
    RoutineConstraint,
    RoutinePlacement,
    RoutinePlan,
    RoutinePlanRequest,
    RoutineValidationRequest,
    RoutineValidationResult,
    Weekday,
)
from agent.schemas import (
    AgentModel,
    Artifact,
    ArtifactLookupRequest,
    ArtifactLookupResult,
    AuthorizedRoom,
    BeginTurnRequest,
    BeginTurnResult,
    ChatMessage,
    ChatTurnInput,
    ChatTurnOutput,
    CompleteTurnRequest,
    Intent,
    MarkTurnFailedRequest,
    MessagePage,
    MessagePageRequest,
    MessageRole,
    ParsedRequest,
    RegisterRoomRequest,
    RoomLookupRequest,
    SaveSummaryRequest,
    SaveSummaryResult,
    SessionContextRequest,
    SessionContextResult,
    SessionSnapshot,
    StageTurnResultRequest,
    SummarySaveStatus,
    TurnBeginStatus,
    TurnFailureCode,
    TurnIdentifiers,
    UnderstandingRequest,
)

FIXTURE_VERSION = "demo-v1"
FIXTURE_CHECKED_AT = "2026-09-09"


class InMemoryTurnRecord(AgentModel):
    turn: ChatTurnInput
    identifiers: TurnIdentifiers
    input_fingerprint: str = Field(min_length=1)
    status: TurnBeginStatus
    output: ChatTurnOutput | None = None
    snapshot: SessionSnapshot | None = None
    failure_code: TurnFailureCode | None = None
    failure_detail: str | None = None
    user_message: ChatMessage


class FakeLlmClient(LlmClient):
    """정해진 한국어 시나리오만 해석하는 테스트 대체 모델."""

    _PRODUCT_KEYWORDS = ("추천", "찾아", "대체")
    _ROUTINE_KEYWORDS = ("루틴", "일정", "요일", "순서", "짜줘", "어떻게 써", "사용 계획")
    _EVIDENCE_KEYWORDS = (
        "효능",
        "근거",
        "역할",
        "병용",
        "같이",
        "괜찮",
        "주의",
        "성분",
        "농도",
        "pH",
    )
    _INGREDIENT_PATTERN = re.compile(
        r"글리세린|글리세롤|세라마이드|판테놀|나이아신아마이드|레티놀|"
        r"glycerin|ceramide|panthenol|niacinamide|retinol",
        re.IGNORECASE,
    )
    _MODIFICATION_KEYWORDS = ("바꿔", "빼줘", "제외", "싫어", "더 가벼운", "수정")
    _EXPERIENCE_KEYWORDS = ("따가", "가려", "붉어", "건조해", "자극")
    _CANDIDATE_PATTERN = re.compile(r"(?P<number>\d+)\s*번")
    _WEEKDAY_KEYWORDS: ClassVar[dict[Weekday, tuple[str, ...]]] = {
        Weekday.MONDAY: ("월요일", "월욜"),
        Weekday.TUESDAY: ("화요일", "화욜"),
        Weekday.WEDNESDAY: ("수요일", "수욜"),
        Weekday.THURSDAY: ("목요일", "목욜"),
        Weekday.FRIDAY: ("금요일", "금욜"),
        Weekday.SATURDAY: ("토요일", "토욜", "주말"),
        Weekday.SUNDAY: ("일요일", "일욜", "주말"),
    }

    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        message = request.message.strip()
        pending = request.context.pending_question
        explicit = self._extract_intents(message, [])
        # 제품명만 답한 경우와 명시적으로 다른 작업을 요청한 경우를 구분한다.
        pending_answer = pending is not None and explicit == [Intent.CLARIFICATION]
        intents = list(pending.original_intents) if pending_answer and pending else explicit
        if intents == [Intent.CLARIFICATION] and pending is None:
            if request.context.routine and self._contains(message, self._MODIFICATION_KEYWORDS):
                intents = [Intent.ROUTINE_PLANNING]
            elif request.context.candidate_set and (
                self._extract_texture(message)
                or self._contains(message, self._MODIFICATION_KEYWORDS)
            ):
                intents = [Intent.PRODUCT_DISCOVERY]
        if pending and explicit == pending.original_intents:
            pending_answer = True
        candidate_number = self._extract_candidate_number(message)
        rejected_numbers = self._extract_rejected_numbers(message, candidate_number)
        return ParsedRequest(
            intents=intents,
            query=message,
            category=self._extract_category(message),
            texture=self._extract_texture(message),
            referenced_candidate_number=candidate_number,
            rejected_candidate_numbers=rejected_numbers,
            excluded_weekdays=self._extract_excluded_weekdays(message),
            reported_experiences=(
                [message] if self._contains(message, self._EXPERIENCE_KEYWORDS) else []
            ),
            is_modification=self._contains(message, self._MODIFICATION_KEYWORDS),
            pending_answer=pending_answer,
            ingredient_mentions=list(dict.fromkeys(self._INGREDIENT_PATTERN.findall(message))),
        )

    def _extract_intents(self, message: str, pending_intents: list[Intent]) -> list[Intent]:
        if "저장" in message:
            if any(word in message for word in ("저장하지", "저장 안", "저장 말")):
                return [Intent.GENERAL_CHAT]
            if self._contains(message, self._MODIFICATION_KEYWORDS):
                return [Intent.ROUTINE_PLANNING, Intent.ROUTINE_SAVE]
            return [Intent.ROUTINE_SAVE]
        if message.rstrip(".!? ") in ("안녕", "안녕하세요", "고마워", "감사합니다"):
            return [Intent.GENERAL_CHAT]
        if any(word in message for word in ("날씨", "주식", "여행", "코딩")):
            return [Intent.OUT_OF_SCOPE]
        intents: list[Intent] = []
        if self._contains(message, self._PRODUCT_KEYWORDS):
            intents.append(Intent.PRODUCT_DISCOVERY)
        if self._contains(message, self._ROUTINE_KEYWORDS):
            intents.append(Intent.ROUTINE_PLANNING)
        if self._contains(message, self._EVIDENCE_KEYWORDS):
            intents.append(Intent.EVIDENCE_QA)
        return intents or [Intent.CLARIFICATION]

    def _extract_candidate_number(self, message: str) -> int | None:
        match = self._CANDIDATE_PATTERN.search(message)
        return int(match.group("number")) if match else None

    def _extract_rejected_numbers(self, message: str, candidate_number: int | None) -> list[int]:
        if candidate_number is None:
            return []
        if "싫" in message or "제외" in message or "빼" in message:
            return [candidate_number]
        return []

    def _extract_category(self, message: str) -> ProductCategory | None:
        if "선크림" in message or "자외선" in message:
            return ProductCategory.SUNSCREEN
        if "클렌저" in message or "세안" in message:
            return ProductCategory.CLEANSER
        if "토너" in message:
            return ProductCategory.TONER
        if "세럼" in message:
            return ProductCategory.SERUM
        if "크림" in message or "보습" in message:
            return ProductCategory.MOISTURIZER
        return None

    def _extract_texture(self, message: str) -> ProductTexture | None:
        if "가벼" in message or "산뜻" in message or "젤" in message:
            return ProductTexture.LIGHT
        if "리치" in message or "꾸덕" in message:
            return ProductTexture.RICH
        return None

    def _extract_excluded_weekdays(self, message: str) -> list[Weekday]:
        if "빼" not in message and "제외" not in message:
            return []
        return [
            weekday
            for weekday, keywords in self._WEEKDAY_KEYWORDS.items()
            if self._contains(message, keywords)
        ]

    def _contains(self, message: str, keywords: Sequence[str]) -> bool:
        return any(keyword in message for keyword in keywords)


class FixtureIngredientRepository(IngredientRepository):
    """실제 성분 사전 연결 전 계약을 검증하는 작은 fixture."""

    def __init__(self) -> None:
        self._ingredients = [
            IngredientRecord(
                ingredient_id="ingredient:glycerin",
                canonical_name="글리세린",
                aliases=["glycerin", "글리세롤"],
            ),
            IngredientRecord(
                ingredient_id="ingredient:ceramide",
                canonical_name="세라마이드",
                aliases=["ceramide"],
            ),
            IngredientRecord(
                ingredient_id="ingredient:panthenol",
                canonical_name="판테놀",
                aliases=["panthenol"],
            ),
            IngredientRecord(
                ingredient_id="ingredient:niacinamide",
                canonical_name="나이아신아마이드",
                aliases=["niacinamide"],
            ),
            IngredientRecord(
                ingredient_id="ingredient:retinol",
                canonical_name="레티놀",
                aliases=["retinol"],
            ),
        ]

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        query = request.name.casefold()
        matches = [
            ingredient
            for ingredient in self._ingredients
            if ingredient.canonical_name.casefold() in query
            or any(alias.casefold() in query for alias in ingredient.aliases)
        ]
        if not matches:
            return IngredientResolveResult(status=LookupStatus.NO_RESULTS)
        if len(matches) == 1:
            return IngredientResolveResult(
                status=LookupStatus.SUCCESS,
                ingredient=matches[0],
            )
        return IngredientResolveResult(
            status=LookupStatus.SUCCESS,
            ambiguous_candidates=matches,
        )


class FixtureProductRepository(ProductRepository):
    """제품 DB가 정해지기 전 필터와 버전 계약을 실행하는 fixture."""

    def __init__(self) -> None:
        self._products = self._build_products()

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        query = request.query.casefold()
        if "가격" in query or "예산" in query or "원 이하" in query:
            return ProductSearchResult(
                status=LookupStatus.UNSUPPORTED,
                unsupported_conditions=["가격 기반 제품 검색은 현재 지원하지 않습니다."],
            )
        explicit_matches = [
            product for product in self._products if product.name.casefold() in query
        ]
        has_filters = any(
            (
                request.filters.category is not None,
                request.filters.texture is not None,
                bool(request.filters.ingredient_ids),
            )
        )
        is_discovery_query = "추천" in query or "찾아" in query or "대체" in query
        if explicit_matches:
            return ProductSearchResult(
                status=LookupStatus.SUCCESS,
                products=explicit_matches[: request.limit],
            )
        candidates = (
            list(self._products)
            if request.allow_discovery and (has_filters or is_discovery_query)
            else []
        )
        filtered = [product for product in candidates if self._matches_filters(product, request)]
        products = filtered[: request.limit]
        status = LookupStatus.SUCCESS if products else LookupStatus.NO_RESULTS
        return ProductSearchResult(status=status, products=products)

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        for product in self._products:
            version_matches = request.version is None or request.version == product.version
            if product.product_id == request.product_id and version_matches:
                return ProductGetResult(status=LookupStatus.SUCCESS, product=product)
        return ProductGetResult(status=LookupStatus.NO_RESULTS)

    def _matches_filters(self, product: ProductRecord, request: ProductSearchRequest) -> bool:
        filters = request.filters
        if filters.category is not None and product.category is not filters.category:
            return False
        if filters.texture is not None and product.texture is not filters.texture:
            return False
        return not filters.ingredient_ids or set(filters.ingredient_ids).issubset(
            product.ingredient_ids
        )

    def _build_products(self) -> list[ProductRecord]:
        return [
            ProductRecord(
                product_id="product:ceramide-cream",
                version=FIXTURE_VERSION,
                name="데모 세라마이드 크림",
                category=ProductCategory.MOISTURIZER,
                texture=ProductTexture.RICH,
                ingredient_ids=["ingredient:ceramide", "ingredient:glycerin"],
                directions="개발 fixture: 저녁 보습 단계에 사용",
                source_id="demo-product-catalog",
                checked_at=FIXTURE_CHECKED_AT,
            ),
            ProductRecord(
                product_id="product:panthenol-gel",
                version=FIXTURE_VERSION,
                name="데모 판테놀 젤 크림",
                category=ProductCategory.MOISTURIZER,
                texture=ProductTexture.LIGHT,
                ingredient_ids=["ingredient:panthenol", "ingredient:glycerin"],
                directions="개발 fixture: 아침 또는 저녁 보습 단계에 사용",
                source_id="demo-product-catalog",
                checked_at=FIXTURE_CHECKED_AT,
            ),
            ProductRecord(
                product_id="product:niacinamide-serum",
                version=FIXTURE_VERSION,
                name="데모 나이아신아마이드 세럼",
                category=ProductCategory.SERUM,
                texture=ProductTexture.LIGHT,
                ingredient_ids=["ingredient:niacinamide"],
                directions="개발 fixture: 저녁 세럼 단계에 사용",
                source_id="demo-product-catalog",
                checked_at=FIXTURE_CHECKED_AT,
            ),
            ProductRecord(
                product_id="product:retinol-serum",
                version=FIXTURE_VERSION,
                name="데모 레티놀 세럼",
                category=ProductCategory.SERUM,
                texture=ProductTexture.LIGHT,
                ingredient_ids=["ingredient:retinol"],
                directions="개발 fixture: 저녁에만 사용하며 실제 사용 빈도는 별도 확인 필요",
                source_id="demo-product-catalog",
                checked_at=FIXTURE_CHECKED_AT,
            ),
        ]


class CatalogIngredientRepository(IngredientRepository):
    """DB가 정해지기 전에도 주입된 성분 DTO 사전으로 요청 해석을 검증한다."""

    def __init__(self, ingredients: list[IngredientRecord]) -> None:
        self._resolver = IngredientMentionResolver(ingredients)

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        return self._resolver.resolve(request)


class FixtureEvidenceRetriever(EvidenceRetriever):
    """검색 결과와 검색 실패를 구분하는 로컬 키워드 retriever."""

    def __init__(self) -> None:
        self._records = self._build_records()
        self._fail_next_search = False

    def fail_next_search(self) -> None:
        self._fail_next_search = True

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        if self._fail_next_search:
            self._fail_next_search = False
            return EvidenceSearchResult(
                status=LookupStatus.ERROR,
                error_message="개발용 검색 실패가 주입되었습니다.",
            )

        query = request.query.casefold()
        matches = [
            record
            for record in self._records
            if set(request.target_ids).intersection(record.target_ids)
            or any(target.casefold().split(":")[-1] in query for target in record.target_ids)
            or any(keyword in query for keyword in self._keywords(record))
        ]
        records = matches[: request.limit]
        status = LookupStatus.SUCCESS if records else LookupStatus.NO_RESULTS
        return EvidenceSearchResult(status=status, records=records)

    def _keywords(self, record: EvidenceRecord) -> list[str]:
        aliases: dict[str, list[str]] = {
            "ingredient:glycerin": ["글리세린", "glycerin"],
            "ingredient:ceramide": ["세라마이드", "ceramide"],
            "ingredient:panthenol": ["판테놀", "panthenol"],
            "ingredient:niacinamide": ["나이아신아마이드", "niacinamide"],
            "ingredient:retinol": ["레티놀", "retinol"],
        }
        return [alias for target in record.target_ids for alias in aliases.get(target, [])]

    def _build_records(self) -> list[EvidenceRecord]:
        return [
            self._record(
                evidence_id="demo-evidence:glycerin",
                target_id="ingredient:glycerin",
                text="개발 fixture에서는 글리세린을 보습 역할의 검색 예시로만 설명합니다.",
                usage="제품 전체 제형과 농도는 미상",
            ),
            self._record(
                evidence_id="demo-evidence:ceramide",
                target_id="ingredient:ceramide",
                text="개발 fixture에서는 세라마이드를 피부 장벽 관련 검색 예시로만 설명합니다.",
                usage="실제 제품 적용성은 별도 검수 필요",
            ),
            self._record(
                evidence_id="demo-evidence:panthenol",
                target_id="ingredient:panthenol",
                text="개발 fixture에서는 판테놀을 보습과 진정 관련 검색 예시로만 설명합니다.",
                usage="실제 제품 적용성은 별도 검수 필요",
            ),
            self._record(
                evidence_id="demo-evidence:niacinamide",
                target_id="ingredient:niacinamide",
                text="개발 fixture에서는 나이아신아마이드를 성분 설명 흐름 검증에만 사용합니다.",
                usage="농도와 완제품 근거는 포함하지 않음",
            ),
            self._record(
                evidence_id="demo-evidence:retinol",
                target_id="ingredient:retinol",
                text="개발 fixture에서는 레티놀 질문에 조건 확인이 필요함을 보여주는 용도입니다.",
                usage="빈도와 내약성에 대한 실제 임상 판단 불가",
            ),
        ]

    def _record(
        self,
        evidence_id: str,
        target_id: str,
        text: str,
        usage: str,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=evidence_id,
            source_id="demo-evidence-catalog",
            source_type=EvidenceSourceType.DEMO,
            source_title="개발용 근거 fixture (실제 임상 근거 아님)",
            document_version=FIXTURE_VERSION,
            text=text,
            locator=f"fixture:{target_id}",
            target_ids=[target_id],
            conditions=EvidenceConditions(usage=usage),
            review_status=EvidenceReviewStatus.DEMO,
            is_demo=True,
        )


class FixtureRoutinePlanner(RoutinePlanner):
    """임상 최적화가 아니라 구조화된 배치·검증 흐름만 보여주는 계획기."""

    _WEEKDAY_ORDER: ClassVar[tuple[Weekday, ...]] = (
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
        Weekday.THURSDAY,
        Weekday.FRIDAY,
        Weekday.SATURDAY,
        Weekday.SUNDAY,
    )

    async def plan(self, request: RoutinePlanRequest) -> RoutinePlan:
        available_days = [
            weekday for weekday in self._WEEKDAY_ORDER if weekday not in request.excluded_weekdays
        ]
        selected_days = available_days[: request.frequency_per_week]
        previous_version = request.current_plan.version if request.current_plan else 0
        routine_id = (
            request.current_plan.routine_id
            if request.current_plan
            else str(uuid5(NAMESPACE_URL, f"routine:{request.chat_room_id}"))
        )
        placements: list[RoutinePlacement] = []
        for weekday in selected_days:
            for order, product in enumerate(request.products, start=1):
                placements.append(
                    RoutinePlacement(
                        weekday=weekday,
                        period=DayPeriod.EVENING,
                        product_id=product.product_id,
                        product_name=product.name,
                        order=order,
                        reason="개발용 배치 정책과 제품 fixture 사용 맥락을 적용",
                    )
                )

        constraints = [
            RoutineConstraint(
                description="실제 임상 빈도가 아닌 개발용 기본 주 2회 배치",
                source=ConstraintSource.SERVICE_POLICY,
            )
        ]
        constraints.extend(
            RoutineConstraint(
                description=product.directions,
                source=ConstraintSource.PRODUCT_DIRECTIONS,
                source_id=product.source_id,
            )
            for product in request.products
        )
        constraints.extend(
            RoutineConstraint(
                description=f"{weekday.value} 제외",
                source=ConstraintSource.USER,
            )
            for weekday in request.excluded_weekdays
        )
        changes = (
            ["사용자 변경 조건을 반영해 전체 일정을 다시 계산함"] if request.current_plan else []
        )
        return RoutinePlan(
            routine_id=routine_id,
            version=previous_version + 1,
            placements=placements,
            constraints=constraints,
            changes=changes,
            is_demo=True,
        )

    async def validate(self, request: RoutineValidationRequest) -> RoutineValidationResult:
        violations: list[str] = []
        for placement in request.plan.placements:
            if placement.weekday in request.excluded_weekdays:
                violations.append(f"제외 요일에 제품이 배치되었습니다: {placement.weekday.value}")
        if not request.plan.placements:
            violations.append("사용 가능한 요일이 없어 배치가 비어 있습니다.")
        return RoutineValidationResult(valid=not violations, violations=violations)


class InMemoryChatHistoryRepository(ChatHistoryRepository):
    """방 격리·중복 요청·완료 스냅샷 계약을 검증하는 개발 저장소."""

    def __init__(self) -> None:
        self._rooms: dict[str, AuthorizedRoom] = {}
        self._messages: dict[str, list[ChatMessage]] = {}
        self._turns: dict[str, dict[str, InMemoryTurnRecord]] = {}
        self._snapshots: dict[str, SessionSnapshot] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_request_ids: dict[str, str] = {}
        self._fail_next_complete = False

    def register_room(self, request: RegisterRoomRequest) -> None:
        existing = self._rooms.get(request.chat_room_id)
        if existing and (
            existing.actor_id != request.actor_id or existing.thread_id != request.thread_id
        ):
            raise TurnStorageError("이미 등록된 방의 소유자 또는 thread_id를 바꿀 수 없습니다.")
        if any(
            room.thread_id == request.thread_id and room.chat_room_id != request.chat_room_id
            for room in self._rooms.values()
        ):
            raise TurnStorageError("다른 채팅방이 사용하는 thread_id입니다.")
        room = AuthorizedRoom(
            actor_id=request.actor_id,
            chat_room_id=request.chat_room_id,
            thread_id=request.thread_id,
        )
        self._rooms[request.chat_room_id] = room
        self._messages.setdefault(request.chat_room_id, [])
        self._turns.setdefault(request.chat_room_id, {})
        self._locks.setdefault(request.chat_room_id, asyncio.Lock())

    def fail_next_complete(self) -> None:
        self._fail_next_complete = True

    async def get_authorized_room(self, request: RoomLookupRequest) -> AuthorizedRoom:
        room = self._rooms.get(request.chat_room_id)
        if room is None:
            raise RoomNotFoundError(f"채팅방을 찾을 수 없습니다: {request.chat_room_id}")
        if room.actor_id != request.actor_id:
            raise RoomAccessDeniedError(f"채팅방 접근 권한이 없습니다: {request.chat_room_id}")
        return room.model_copy(deep=True)

    async def begin_turn(self, request: BeginTurnRequest) -> BeginTurnResult:
        lock = self._locks[request.room.chat_room_id]
        async with lock:
            room_turns = self._turns[request.room.chat_room_id]
            existing = room_turns.get(request.turn.request_id)
            if existing is not None:
                if existing.input_fingerprint != request.input_fingerprint:
                    return BeginTurnResult(status=TurnBeginStatus.CONFLICT)
                if existing.status is TurnBeginStatus.COMPLETED:
                    return BeginTurnResult(
                        status=TurnBeginStatus.COMPLETED,
                        output=existing.output.model_copy(deep=True) if existing.output else None,
                        snapshot=(
                            existing.snapshot.model_copy(deep=True) if existing.snapshot else None
                        ),
                    )
                if existing.status is TurnBeginStatus.STAGED:
                    return BeginTurnResult(
                        status=TurnBeginStatus.STAGED,
                        output=existing.output.model_copy(deep=True) if existing.output else None,
                        snapshot=(
                            existing.snapshot.model_copy(deep=True) if existing.snapshot else None
                        ),
                    )
                if existing.status is TurnBeginStatus.IN_PROGRESS:
                    return BeginTurnResult(status=TurnBeginStatus.IN_PROGRESS)
                active = self._active_request_ids.get(request.room.chat_room_id)
                if active is not None and active != request.turn.request_id:
                    return BeginTurnResult(status=TurnBeginStatus.IN_PROGRESS)
                snapshot = self._snapshots.get(request.room.chat_room_id)
                if snapshot and any(
                    message.sequence > existing.user_message.sequence
                    for message in snapshot.messages
                ):
                    return BeginTurnResult(status=TurnBeginStatus.CONFLICT)
                existing.status = TurnBeginStatus.IN_PROGRESS
                existing.failure_code = None
                existing.failure_detail = None
                self._active_request_ids[request.room.chat_room_id] = request.turn.request_id
                return BeginTurnResult(
                    status=TurnBeginStatus.NEW,
                    user_message=existing.user_message.model_copy(deep=True),
                )

            active_request_id = self._active_request_ids.get(request.room.chat_room_id)
            if active_request_id is not None:
                return BeginTurnResult(status=TurnBeginStatus.IN_PROGRESS)

            user_message = ChatMessage(
                message_id=request.identifiers.user_message_id,
                request_id=request.turn.request_id,
                role=MessageRole.USER,
                content=request.turn.message,
                sequence=len(self._messages[request.room.chat_room_id]) + 1,
            )
            self._messages[request.room.chat_room_id].append(user_message)
            room_turns[request.turn.request_id] = InMemoryTurnRecord(
                turn=request.turn,
                identifiers=request.identifiers,
                input_fingerprint=request.input_fingerprint,
                status=TurnBeginStatus.IN_PROGRESS,
                user_message=user_message,
            )
            self._active_request_ids[request.room.chat_room_id] = request.turn.request_id
            return BeginTurnResult(
                status=TurnBeginStatus.NEW,
                user_message=user_message.model_copy(deep=True),
            )

    async def get_messages(self, request: MessagePageRequest) -> MessagePage:
        messages = [
            message
            for message in self._messages[request.room.chat_room_id]
            if message.sequence > request.after_sequence
        ]
        page = messages[: request.limit]
        return MessagePage(
            messages=[message.model_copy(deep=True) for message in page],
            has_more=len(messages) > len(page),
        )

    async def get_artifacts(self, request: ArtifactLookupRequest) -> ArtifactLookupResult:
        artifacts: list[Artifact] = []
        for record in self._turns[request.room.chat_room_id].values():
            if record.status is not TurnBeginStatus.COMPLETED or record.output is None:
                continue
            for artifact in record.output.artifacts:
                candidate_matches = (
                    request.candidate_set_id is not None
                    and isinstance(artifact, ProductCandidateSet)
                    and artifact.candidate_set_id == request.candidate_set_id
                )
                routine_matches = (
                    request.routine_id is not None
                    and isinstance(artifact, RoutinePlan)
                    and artifact.routine_id == request.routine_id
                    and (
                        request.routine_version is None
                        or artifact.version == request.routine_version
                    )
                )
                if candidate_matches or routine_matches:
                    artifacts.append(artifact.model_copy(deep=True))
        return ArtifactLookupResult(artifacts=artifacts)

    async def get_session_context(self, request: SessionContextRequest) -> SessionContextResult:
        snapshot = self._snapshots.get(request.room.chat_room_id)
        return SessionContextResult(snapshot=snapshot.model_copy(deep=True) if snapshot else None)

    async def stage_turn_result(self, request: StageTurnResultRequest) -> None:
        lock = self._locks[request.room.chat_room_id]
        async with lock:
            record = self._get_turn(request.room, request.request_id)
            record.output = request.output.model_copy(deep=True)
            record.snapshot = request.snapshot.model_copy(deep=True)
            record.status = TurnBeginStatus.STAGED

    async def complete_turn(self, request: CompleteTurnRequest) -> None:
        lock = self._locks[request.room.chat_room_id]
        async with lock:
            if self._fail_next_complete:
                self._fail_next_complete = False
                raise TurnStorageError("개발용 응답 저장 실패가 주입되었습니다.")

            record = self._get_turn(request.room, request.request_id)
            if record.status is TurnBeginStatus.COMPLETED:
                return
            if record.output != request.output or record.snapshot != request.snapshot:
                raise TurnStorageError("스테이징된 생성 결과와 완료 요청이 일치하지 않습니다.")
            assistant_message = ChatMessage(
                message_id=request.output.assistant_message_id,
                request_id=request.request_id,
                role=MessageRole.ASSISTANT,
                content=request.output.message,
                sequence=len(self._messages[request.room.chat_room_id]) + 1,
            )
            self._messages[request.room.chat_room_id].append(assistant_message)
            previous = self._snapshots.get(request.room.chat_room_id)
            revision = previous.source_revision + 1 if previous else 1
            snapshot = request.snapshot.model_copy(
                update={"source_revision": revision},
                deep=True,
            )
            snapshot.messages = [
                assistant_message.model_copy(deep=True)
                if message.message_id == assistant_message.message_id
                else message
                for message in snapshot.messages
            ]
            self._snapshots[request.room.chat_room_id] = snapshot
            record.output = request.output.model_copy(deep=True)
            record.snapshot = snapshot.model_copy(deep=True)
            record.status = TurnBeginStatus.COMPLETED
            self._active_request_ids.pop(request.room.chat_room_id, None)

    async def mark_turn_failed(self, request: MarkTurnFailedRequest) -> None:
        lock = self._locks[request.room.chat_room_id]
        async with lock:
            record = self._get_turn(request.room, request.request_id)
            if record.status is TurnBeginStatus.COMPLETED:
                return
            record.status = TurnBeginStatus.FAILED
            record.failure_code = request.failure_code
            record.failure_detail = request.detail
            self._active_request_ids.pop(request.room.chat_room_id, None)

    async def save_summary(self, request: SaveSummaryRequest) -> SaveSummaryResult:
        lock = self._locks[request.room.chat_room_id]
        async with lock:
            snapshot = self._snapshots.get(request.room.chat_room_id)
            if snapshot is None:
                return SaveSummaryResult(
                    status=SummarySaveStatus.NO_SNAPSHOT,
                    source_revision=0,
                )
            if snapshot.source_revision != request.expected_revision:
                return SaveSummaryResult(
                    status=SummarySaveStatus.REVISION_CONFLICT,
                    source_revision=snapshot.source_revision,
                )
            next_revision = snapshot.source_revision + 1
            self._snapshots[request.room.chat_room_id] = snapshot.model_copy(
                update={
                    "summary": request.summary.model_copy(deep=True),
                    "source_revision": next_revision,
                },
                deep=True,
            )
            return SaveSummaryResult(
                status=SummarySaveStatus.SAVED,
                source_revision=next_revision,
            )

    def _get_turn(self, room: AuthorizedRoom, request_id: str) -> InMemoryTurnRecord:
        record = self._turns[room.chat_room_id].get(request_id)
        if record is None:
            raise TurnStorageError(f"등록되지 않은 요청입니다: {request_id}")
        return record
