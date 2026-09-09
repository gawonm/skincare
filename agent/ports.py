"""에이전트가 외부 저장소와 모델을 호출할 때 사용하는 계약."""

from abc import ABC, abstractmethod

from agent.rag.schemas import (
    IngredientResolveRequest,
    IngredientResolveResult,
    ProductGetRequest,
    ProductGetResult,
    ProductSearchRequest,
    ProductSearchResult,
    RoutinePlan,
    RoutinePlanRequest,
    RoutineValidationRequest,
    RoutineValidationResult,
)
from agent.schemas import (
    ArtifactLookupRequest,
    ArtifactLookupResult,
    AuthorizedRoom,
    BeginTurnRequest,
    BeginTurnResult,
    CompleteTurnRequest,
    MarkTurnFailedRequest,
    MessagePage,
    MessagePageRequest,
    ParsedRequest,
    RoomLookupRequest,
    SaveSummaryRequest,
    SaveSummaryResult,
    SessionContextRequest,
    SessionContextResult,
    StageTurnResultRequest,
    UnderstandingRequest,
)


class RoomNotFoundError(LookupError):
    """요청한 채팅방이 존재하지 않을 때 사용한다."""


class RoomAccessDeniedError(PermissionError):
    """인증 주체가 채팅방 소유자가 아닐 때 사용한다."""


class TurnStorageError(RuntimeError):
    """턴 결과를 일관되게 저장하지 못했을 때 사용한다."""


class ProductRepository(ABC):
    @abstractmethod
    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        raise NotImplementedError

    @abstractmethod
    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        raise NotImplementedError


class IngredientRepository(ABC):
    @abstractmethod
    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        raise NotImplementedError


class RoutinePlanner(ABC):
    @abstractmethod
    async def plan(self, request: RoutinePlanRequest) -> RoutinePlan:
        raise NotImplementedError

    @abstractmethod
    async def validate(self, request: RoutineValidationRequest) -> RoutineValidationResult:
        raise NotImplementedError


class LlmClient(ABC):
    @abstractmethod
    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        raise NotImplementedError


class ChatHistoryRepository(ABC):
    @abstractmethod
    async def get_authorized_room(self, request: RoomLookupRequest) -> AuthorizedRoom:
        raise NotImplementedError

    @abstractmethod
    async def begin_turn(self, request: BeginTurnRequest) -> BeginTurnResult:
        raise NotImplementedError

    @abstractmethod
    async def get_messages(self, request: MessagePageRequest) -> MessagePage:
        raise NotImplementedError

    @abstractmethod
    async def get_artifacts(self, request: ArtifactLookupRequest) -> ArtifactLookupResult:
        raise NotImplementedError

    @abstractmethod
    async def get_session_context(self, request: SessionContextRequest) -> SessionContextResult:
        raise NotImplementedError

    @abstractmethod
    async def stage_turn_result(self, request: StageTurnResultRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    async def complete_turn(self, request: CompleteTurnRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    async def mark_turn_failed(self, request: MarkTurnFailedRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    async def save_summary(self, request: SaveSummaryRequest) -> SaveSummaryResult:
        raise NotImplementedError
