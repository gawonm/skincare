"""채팅 턴 등록, 그래프 실행, 결과 저장을 조정하는 비동기 진입점."""

import asyncio
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from agent.graph import AgentGraph
from agent.ports import (
    ChatHistoryRepository,
    RoomAccessDeniedError,
    RoomNotFoundError,
    TurnStorageError,
)
from agent.schemas import (
    AgentInvocation,
    AuthorizedRoom,
    BeginTurnRequest,
    BeginTurnResult,
    ChatServiceRequest,
    ChatStatus,
    ChatTurnInput,
    ChatTurnOutput,
    CompleteTurnRequest,
    ContextLimits,
    ErrorCode,
    ExecutionLimits,
    GraphInvocationRequest,
    MarkTurnFailedRequest,
    RoomLookupRequest,
    SessionContextRequest,
    StageTurnResultRequest,
    TurnBeginStatus,
    TurnFailureCode,
    TurnIdentifiers,
)


class RequestIdentityFactory:
    """재시도에도 같은 메시지 ID와 입력 fingerprint를 만든다."""

    def create_identifiers(self, turn: ChatTurnInput) -> TurnIdentifiers:
        base = f"{turn.chat_room_id}:{turn.request_id}"
        return TurnIdentifiers(
            user_message_id=str(uuid5(NAMESPACE_URL, f"user:{base}")),
            assistant_message_id=str(uuid5(NAMESPACE_URL, f"assistant:{base}")),
        )

    def create_fingerprint(self, turn: ChatTurnInput) -> str:
        encoded = turn.model_dump_json().encode("utf-8")
        return sha256(encoded).hexdigest()


class ChatService:
    """백엔드가 호출할 수 있는 LLM·RAG 계층의 단일 진입점."""

    def __init__(
        self,
        graph: AgentGraph,
        history: ChatHistoryRepository,
        identity_factory: RequestIdentityFactory,
        execution_limits: ExecutionLimits,
        context_limits: ContextLimits,
    ) -> None:
        self._graph = graph
        self._history = history
        self._identity_factory = identity_factory
        self._execution_limits = execution_limits
        self._context_limits = context_limits

    async def handle_turn(self, request: ChatServiceRequest) -> ChatTurnOutput:
        identifiers = self._identity_factory.create_identifiers(request.turn)
        if request.auth.chat_room_id != request.turn.chat_room_id:
            return self._error_output(
                request.turn,
                identifiers,
                ErrorCode.REQUEST_CONFLICT,
                "인증된 채팅방과 입력의 채팅방이 다릅니다.",
                retryable=False,
            )

        try:
            room = await self._history.get_authorized_room(
                RoomLookupRequest(
                    actor_id=request.auth.actor_id,
                    chat_room_id=request.auth.chat_room_id,
                )
            )
        except RoomNotFoundError as error:
            return self._error_output(
                request.turn,
                identifiers,
                ErrorCode.ROOM_NOT_FOUND,
                str(error),
                retryable=False,
            )
        except RoomAccessDeniedError as error:
            return self._error_output(
                request.turn,
                identifiers,
                ErrorCode.ROOM_FORBIDDEN,
                str(error),
                retryable=False,
            )

        begin_result = await self._history.begin_turn(
            BeginTurnRequest(
                room=room,
                turn=request.turn,
                identifiers=identifiers,
                input_fingerprint=self._identity_factory.create_fingerprint(request.turn),
            )
        )
        if begin_result.status is TurnBeginStatus.COMPLETED:
            if begin_result.output is None:
                raise RuntimeError("완료된 요청에 저장된 응답이 없습니다.")
            return begin_result.output
        if begin_result.status is TurnBeginStatus.CONFLICT:
            return self._error_output(
                request.turn,
                identifiers,
                ErrorCode.REQUEST_CONFLICT,
                "같은 request_id에 다른 입력 본문이 사용되었습니다.",
                retryable=False,
            )
        if begin_result.status is TurnBeginStatus.IN_PROGRESS:
            return self._error_output(
                request.turn,
                identifiers,
                ErrorCode.REQUEST_IN_PROGRESS,
                "같은 채팅방의 요청이 이미 처리 중입니다.",
                retryable=True,
            )
        if begin_result.status is TurnBeginStatus.STAGED:
            return await self._complete_staged_turn(request.turn, room, begin_result)

        try:
            session_context = await self._history.get_session_context(
                SessionContextRequest(room=room)
            )
            invocation = AgentInvocation(
                chat_room_id=room.chat_room_id,
                thread_id=room.thread_id,
                turn_input=request.turn,
                identifiers=identifiers,
                execution_limits=self._execution_limits,
                context_limits=self._context_limits,
                restored_snapshot=session_context.snapshot,
                user_message=begin_result.user_message,
            )
            graph_result = await self._graph.ainvoke(
                GraphInvocationRequest(
                    invocation=invocation,
                    recursion_limit=self._execution_limits.recursion_limit,
                )
            )
            if graph_result.state.output is None:
                raise RuntimeError("그래프가 구조화된 최종 응답을 만들지 않았습니다.")
        except asyncio.CancelledError:
            await self._history.mark_turn_failed(
                MarkTurnFailedRequest(
                    room=room,
                    request_id=request.turn.request_id,
                    failure_code=TurnFailureCode.GRAPH,
                    detail="요청 실행이 취소되었습니다.",
                    retryable=True,
                )
            )
            raise
        except (
            ConnectionError,
            OSError,
            RecursionError,
            RuntimeError,
            TimeoutError,
            TypeError,
            ValueError,
        ) as error:
            await self._history.mark_turn_failed(
                MarkTurnFailedRequest(
                    room=room,
                    request_id=request.turn.request_id,
                    failure_code=TurnFailureCode.GRAPH,
                    detail=f"{type(error).__name__}: {error}",
                    retryable=True,
                )
            )
            return self._error_output(
                request.turn,
                identifiers,
                (
                    ErrorCode.EXECUTION_LIMIT_REACHED
                    if isinstance(error, TimeoutError)
                    else ErrorCode.GRAPH_EXECUTION_FAILED
                ),
                f"문맥 복원 또는 그래프 실행 실패: {type(error).__name__}: {error}",
                retryable=True,
            )

        output = graph_result.state.output
        if output is None:
            raise RuntimeError("그래프가 구조화된 최종 응답을 만들지 않았습니다.")
        stage_request = StageTurnResultRequest(
            room=room,
            request_id=request.turn.request_id,
            output=output,
            snapshot=graph_result.state.to_session_snapshot(),
        )
        try:
            await self._history.stage_turn_result(stage_request)
        except TurnStorageError as error:
            await self._history.mark_turn_failed(
                MarkTurnFailedRequest(
                    room=room,
                    request_id=request.turn.request_id,
                    failure_code=TurnFailureCode.STORAGE,
                    detail=f"{type(error).__name__}: {error}",
                    retryable=True,
                )
            )
            return self._error_output(
                request.turn,
                identifiers,
                ErrorCode.RESPONSE_SAVE_FAILED,
                f"생성 결과 임시 저장 실패: {error}",
                retryable=True,
            )
        try:
            await self._history.complete_turn(
                CompleteTurnRequest(
                    room=stage_request.room,
                    request_id=stage_request.request_id,
                    output=stage_request.output,
                    snapshot=stage_request.snapshot,
                )
            )
        except TurnStorageError as error:
            return self._error_output(
                request.turn,
                identifiers,
                ErrorCode.RESPONSE_SAVE_FAILED,
                f"응답 저장 실패: {error}",
                retryable=True,
            )
        return output

    async def _complete_staged_turn(
        self,
        turn: ChatTurnInput,
        room: AuthorizedRoom,
        begin_result: BeginTurnResult,
    ) -> ChatTurnOutput:
        if begin_result.output is None or begin_result.snapshot is None:
            raise RuntimeError("저장 재시도 상태에 생성 결과 또는 스냅샷이 없습니다.")
        try:
            await self._history.complete_turn(
                CompleteTurnRequest(
                    room=room,
                    request_id=turn.request_id,
                    output=begin_result.output,
                    snapshot=begin_result.snapshot,
                )
            )
        except TurnStorageError as error:
            identifiers = self._identity_factory.create_identifiers(turn)
            return self._error_output(
                turn,
                identifiers,
                ErrorCode.RESPONSE_SAVE_FAILED,
                f"응답 저장 재시도 실패: {error}",
                retryable=True,
            )
        return begin_result.output

    def _error_output(
        self,
        turn: ChatTurnInput,
        identifiers: TurnIdentifiers,
        error_code: ErrorCode,
        message: str,
        retryable: bool,
    ) -> ChatTurnOutput:
        return ChatTurnOutput(
            chat_room_id=turn.chat_room_id,
            request_id=turn.request_id,
            assistant_message_id=identifiers.assistant_message_id,
            status=ChatStatus.ERROR,
            message=message,
            error_code=error_code,
            retryable=retryable,
        )
