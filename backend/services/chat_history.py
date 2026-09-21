"""Agent의 `ChatHistoryRepository` 포트를 `chat_room`/`chat_message`/`chat_turn_state`로 구현한다.

Agent는 DB 세션과 트랜잭션을 모른다. 그래서 포트 메서드 하나가 트랜잭션 하나이고 commit은 여기서
한다. 특히 `begin_turn`은 진행 중 표시를 바로 커밋해야 같은 방의 동시 요청이 그것을 볼 수 있다.

같은 방의 턴 시작·확정은 방 행을 `FOR UPDATE`로 잠가 한 번에 하나씩 처리한다. 잠금은 트랜잭션이
끝나면 풀리고, 그 뒤로는 `chat_turn_state`의 진행 중 행이 논리적 잠금 역할을 한다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, JsonValue, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.ports import (
    ChatHistoryRepository,
    RoomAccessDeniedError,
    RoomNotFoundError,
    TurnStorageError,
)
from agent.rag.schemas import ProductCandidateSet, RoutinePlan
from agent.schemas import (
    DEFAULT_TIMEOUT_SECONDS,
    Artifact,
    ArtifactLookupRequest,
    ArtifactLookupResult,
    AuthorizedRoom,
    BeginTurnRequest,
    BeginTurnResult,
    ChatMessage,
    ChatTurnOutput,
    CompleteTurnRequest,
    ConversationSummary,
    MarkTurnFailedRequest,
    MessagePage,
    MessagePageRequest,
    MessageRole,
    RoomLookupRequest,
    SaveSummaryRequest,
    SaveSummaryResult,
    SessionContextRequest,
    SessionContextResult,
    SessionSnapshot,
    StageTurnResultRequest,
    SummarySaveStatus,
    TurnBeginStatus,
)
from backend.repositories.chat_message_repository import ChatMessageRepository
from backend.repositories.chat_room_repository import ChatRoomRepository, ChatRoomSnapshotUpdate
from backend.repositories.chat_turn_state_repository import ChatTurnStateRepository
from models import chat_message as chat_message_models
from models import chat_turn_state as chat_turn_state_models
from models.chat_message import ChatMessage as ChatMessageRow
from models.chat_room import ChatRoom
from models.chat_turn_state import ChatTurnState


class ChatHistoryMapper:
    """DB 행과 JSONB를 Agent DTO로, Agent DTO를 JSON 값으로 바꾼다."""

    def to_uuid(self, value: str, label: str) -> UUID:
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{label}가 UUID 형식이 아닙니다: {value}") from error

    def message_to_dto(self, row: ChatMessageRow) -> ChatMessage:
        return ChatMessage(
            message_id=str(row.id),
            request_id=row.request_id,
            role=MessageRole(row.role.value),
            content=row.content,
            sequence=row.sequence,
            created_at=row.created_at,
        )

    def parse_output(self, turn: ChatTurnState) -> ChatTurnOutput:
        return self._parse(ChatTurnOutput, turn.staged_output, "저장된 응답")

    def parse_snapshot(self, turn: ChatTurnState) -> SessionSnapshot:
        return self._parse(SessionSnapshot, turn.staged_snapshot, "저장된 스냅샷")

    def snapshot_from_room(self, room: ChatRoom, rows: list[ChatMessageRow]) -> SessionSnapshot:
        """방의 JSONB 컬럼과 메시지 행으로 Agent가 복원할 세션 스냅샷을 만든다."""
        payload: dict[str, JsonValue] = {
            "messages": [self.message_to_dto(row).model_dump(mode="json") for row in rows],
            "profile": room.profile,
            "task_context": room.task_context,
            "pending_question": room.pending_question,
            "candidate_set": room.candidate_set,
            "routine": room.routine,
            "evidence": room.evidence,
            "summary": room.summary,
            "schema_version": room.schema_version,
            "source_revision": room.source_revision,
            "last_completed_request_id": room.last_completed_request_id,
        }
        return self._parse(SessionSnapshot, payload, "방 스냅샷")

    def snapshot_to_update(self, snapshot: SessionSnapshot) -> ChatRoomSnapshotUpdate:
        """`messages`는 `chat_message` 행이 원본이라 방 컬럼에 담지 않는다."""
        dumped = snapshot.model_dump(mode="json")
        return ChatRoomSnapshotUpdate(
            schema_version=snapshot.schema_version,
            source_revision=snapshot.source_revision,
            last_completed_request_id=snapshot.last_completed_request_id,
            profile=dumped["profile"],
            task_context=dumped["task_context"],
            pending_question=dumped["pending_question"],
            candidate_set=dumped["candidate_set"],
            routine=dumped["routine"],
            evidence=dumped["evidence"],
            summary=dumped["summary"],
        )

    def _parse[T: BaseModel](self, model: type[T], payload: object, label: str) -> T:
        if payload is None:
            raise TurnStorageError(f"{label}가 없습니다.")
        try:
            return model.model_validate(payload)
        except ValidationError as error:
            raise TurnStorageError(f"{label}를 읽지 못했습니다: {error}") from error


class SqlAlchemyChatHistoryRepository(ChatHistoryRepository):
    """방 권한, 턴 멱등성, 임시 저장과 확정, 세션 스냅샷 복원을 DB로 처리한다."""

    # Agent 실행 제한 시간이 지나도 끝나지 않은 턴은 서버가 중간에 죽은 것으로 본다. 제한 시간과
    # 같게 잡으면 정상적으로 끝나 가는 요청을 실패 처리할 수 있어 여유를 더한다.
    STALE_MARGIN_SECONDS: ClassVar[float] = 60.0

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        stale_after: timedelta | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._stale_after = stale_after or timedelta(
            seconds=DEFAULT_TIMEOUT_SECONDS + self.STALE_MARGIN_SECONDS
        )
        self._mapper = ChatHistoryMapper()

    @asynccontextmanager
    async def _transaction(self, action: str) -> AsyncIterator[AsyncSession]:
        """정상 종료하면 commit, 예외가 나면 rollback한다. DB 오류는 원인을 붙여 저장 오류로 바꾼다."""
        try:
            async with self._session_factory() as session, session.begin():
                yield session
        except SQLAlchemyError as error:
            raise TurnStorageError(
                f"채팅 히스토리 {action} 중 DB 오류가 발생했습니다: {error}"
            ) from error

    async def _lock_room(self, session: AsyncSession, room_id: UUID) -> ChatRoom:
        room = await ChatRoomRepository(session).get_by_id_for_update(room_id)
        if room is None:
            raise TurnStorageError(f"채팅방을 찾을 수 없습니다: {room_id}")
        return room

    async def get_authorized_room(self, request: RoomLookupRequest) -> AuthorizedRoom:
        try:
            room_id = self._mapper.to_uuid(request.chat_room_id, "chat_room_id")
        except ValueError as error:
            raise RoomNotFoundError(f"채팅방을 찾을 수 없습니다: {request.chat_room_id}") from error
        async with self._transaction("방 조회") as session:
            room = await ChatRoomRepository(session).get_by_id(room_id)
            if room is None:
                raise RoomNotFoundError(f"채팅방을 찾을 수 없습니다: {request.chat_room_id}")
            if str(room.user_id) != request.actor_id:
                raise RoomAccessDeniedError(f"채팅방 접근 권한이 없습니다: {request.chat_room_id}")
            return AuthorizedRoom(
                actor_id=request.actor_id,
                chat_room_id=str(room.id),
                thread_id=str(room.thread_id),
            )

    async def begin_turn(self, request: BeginTurnRequest) -> BeginTurnResult:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("턴 시작") as session:
            turns = ChatTurnStateRepository(session)
            await self._lock_room(session, room_id)
            await turns.expire_stale(room_id, self._stale_after)
            existing = await turns.get(room_id, request.turn.request_id)
            if existing is None:
                return await self._begin_new_turn(session, room_id, request)
            return await self._resume_turn(session, room_id, existing, request)

    async def _begin_new_turn(
        self, session: AsyncSession, room_id: UUID, request: BeginTurnRequest
    ) -> BeginTurnResult:
        turns = ChatTurnStateRepository(session)
        messages = ChatMessageRepository(session)
        if await turns.has_active_other(room_id, exclude_request_id=None):
            return BeginTurnResult(status=TurnBeginStatus.IN_PROGRESS)
        user_message = await messages.add(
            message_id=self._mapper.to_uuid(request.identifiers.user_message_id, "user_message_id"),
            room_id=room_id,
            request_id=request.turn.request_id,
            role=chat_message_models.MessageRole.USER,
            content=request.turn.message,
            sequence=await messages.next_sequence(room_id),
        )
        await turns.create(room_id, request.turn.request_id, request.input_fingerprint)
        return BeginTurnResult(
            status=TurnBeginStatus.NEW, user_message=self._mapper.message_to_dto(user_message)
        )

    async def _resume_turn(
        self,
        session: AsyncSession,
        room_id: UUID,
        existing: ChatTurnState,
        request: BeginTurnRequest,
    ) -> BeginTurnResult:
        if existing.input_fingerprint != request.input_fingerprint:
            return BeginTurnResult(status=TurnBeginStatus.CONFLICT)
        status = existing.status
        if status in (
            chat_turn_state_models.TurnStateStatus.COMPLETED,
            chat_turn_state_models.TurnStateStatus.STAGED,
        ):
            return BeginTurnResult(
                status=TurnBeginStatus(status.value),
                output=self._mapper.parse_output(existing),
                snapshot=self._mapper.parse_snapshot(existing),
            )
        if status is chat_turn_state_models.TurnStateStatus.IN_PROGRESS:
            return BeginTurnResult(status=TurnBeginStatus.IN_PROGRESS)

        turns = ChatTurnStateRepository(session)
        messages = ChatMessageRepository(session)
        if await turns.has_active_other(room_id, exclude_request_id=request.turn.request_id):
            return BeginTurnResult(status=TurnBeginStatus.IN_PROGRESS)
        user_message = await messages.get_by_request(
            room_id, request.turn.request_id, chat_message_models.MessageRole.USER
        )
        if user_message is None:
            raise TurnStorageError(
                f"실패한 턴의 사용자 메시지가 없습니다: request_id={request.turn.request_id}"
            )
        # 그 사이 다른 요청이 확정됐다면 이전 질문을 뒤늦게 재실행해 대화 순서를 뒤집지 않는다.
        if await messages.has_completed_after(room_id, user_message.sequence):
            return BeginTurnResult(status=TurnBeginStatus.CONFLICT)
        await turns.mark_in_progress(existing)
        return BeginTurnResult(
            status=TurnBeginStatus.NEW, user_message=self._mapper.message_to_dto(user_message)
        )

    async def get_messages(self, request: MessagePageRequest) -> MessagePage:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("메시지 조회") as session:
            rows = await ChatMessageRepository(session).list_after(
                room_id, request.after_sequence, request.limit + 1
            )
        page = rows[: request.limit]
        return MessagePage(
            messages=[self._mapper.message_to_dto(row) for row in page],
            has_more=len(rows) > len(page),
        )

    async def get_artifacts(self, request: ArtifactLookupRequest) -> ArtifactLookupResult:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("아티팩트 조회") as session:
            turns = await ChatTurnStateRepository(session).find_completed_with_artifact(
                room_id,
                candidate_set_id=request.candidate_set_id,
                routine_id=request.routine_id,
                routine_version=request.routine_version,
            )
            outputs = [self._mapper.parse_output(turn) for turn in turns]
        artifacts = [
            artifact
            for output in outputs
            for artifact in output.artifacts
            if self._matches_artifact(artifact, request)
        ]
        return ArtifactLookupResult(artifacts=artifacts)

    def _matches_artifact(self, artifact: Artifact, request: ArtifactLookupRequest) -> bool:
        """DB는 JSON 포함 여부로 후보를 좁힐 뿐이라, 최종 일치 여부는 타입을 보고 다시 확인한다."""
        if isinstance(artifact, ProductCandidateSet):
            return (
                request.candidate_set_id is not None
                and artifact.candidate_set_id == request.candidate_set_id
            )
        if isinstance(artifact, RoutinePlan):
            return (
                request.routine_id is not None
                and artifact.routine_id == request.routine_id
                and (request.routine_version is None or artifact.version == request.routine_version)
            )
        return False

    async def get_session_context(self, request: SessionContextRequest) -> SessionContextResult:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("세션 문맥 조회") as session:
            room = await ChatRoomRepository(session).get_by_id(room_id)
            if room is None:
                raise RoomNotFoundError(f"채팅방을 찾을 수 없습니다: {request.room.chat_room_id}")
            # 확정된 턴이 하나도 없으면 복원할 스냅샷이 없다.
            if room.last_completed_request_id is None:
                return SessionContextResult(snapshot=None)
            # 요약이 이미 덮은 메시지는 Agent가 다시 쓰지 않는다. 덮이지 않은 확정 메시지는 전부
            # 줘야 요약되기 전에 중간 메시지가 조용히 사라지지 않는다.
            summary = self._parse_summary(room)
            covered_sequence = summary.covered_through_sequence if summary else 0
            rows = await ChatMessageRepository(session).list_completed_after(
                room_id, covered_sequence
            )
            snapshot = self._mapper.snapshot_from_room(room, rows)
        return SessionContextResult(snapshot=snapshot)

    def _parse_summary(self, room: ChatRoom) -> ConversationSummary | None:
        if room.summary is None:
            return None
        try:
            return ConversationSummary.model_validate(room.summary)
        except ValidationError as error:
            raise TurnStorageError(f"저장된 요약을 읽지 못했습니다: {error}") from error

    async def stage_turn_result(self, request: StageTurnResultRequest) -> None:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("결과 임시 저장") as session:
            await self._lock_room(session, room_id)
            turns = ChatTurnStateRepository(session)
            turn = await self._get_turn(turns, room_id, request.request_id)
            await turns.stage(
                turn,
                request.output.model_dump(mode="json"),
                request.snapshot.model_dump(mode="json"),
            )

    async def complete_turn(self, request: CompleteTurnRequest) -> None:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("턴 확정") as session:
            room = await self._lock_room(session, room_id)
            turns = ChatTurnStateRepository(session)
            messages = ChatMessageRepository(session)
            turn = await self._get_turn(turns, room_id, request.request_id)
            if turn.status is chat_turn_state_models.TurnStateStatus.COMPLETED:
                return
            output_json = request.output.model_dump(mode="json")
            snapshot_json = request.snapshot.model_dump(mode="json")
            if turn.staged_output != output_json or turn.staged_snapshot != snapshot_json:
                raise TurnStorageError("임시 저장된 생성 결과와 확정 요청이 일치하지 않습니다.")

            assistant_row = await messages.add(
                message_id=self._mapper.to_uuid(
                    request.output.assistant_message_id, "assistant_message_id"
                ),
                room_id=room_id,
                request_id=request.request_id,
                role=chat_message_models.MessageRole.ASSISTANT,
                content=request.output.message,
                sequence=await messages.next_sequence(room_id),
            )
            assistant_message = self._mapper.message_to_dto(assistant_row)
            final_snapshot = request.snapshot.model_copy(
                update={
                    "source_revision": room.source_revision + 1,
                    "last_completed_request_id": request.request_id,
                    # Agent가 임시로 붙인 순번 대신 DB가 확정한 메시지로 바꿔 넣는다.
                    "messages": [
                        assistant_message
                        if message.message_id == assistant_message.message_id
                        else message
                        for message in request.snapshot.messages
                    ],
                },
                deep=True,
            )
            await ChatRoomRepository(session).apply_snapshot(
                room, self._mapper.snapshot_to_update(final_snapshot)
            )
            await turns.complete(turn, output_json, final_snapshot.model_dump(mode="json"))

    async def mark_turn_failed(self, request: MarkTurnFailedRequest) -> None:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("턴 실패 기록") as session:
            await self._lock_room(session, room_id)
            turns = ChatTurnStateRepository(session)
            turn = await self._get_turn(turns, room_id, request.request_id)
            if turn.status is chat_turn_state_models.TurnStateStatus.COMPLETED:
                return
            await turns.mark_failed(
                turn,
                chat_turn_state_models.TurnFailureCode(request.failure_code.value),
                request.detail,
                request.retryable,
            )

    async def save_summary(self, request: SaveSummaryRequest) -> SaveSummaryResult:
        room_id = self._mapper.to_uuid(request.room.chat_room_id, "chat_room_id")
        async with self._transaction("요약 저장") as session:
            room = await self._lock_room(session, room_id)
            if room.last_completed_request_id is None:
                return SaveSummaryResult(status=SummarySaveStatus.NO_SNAPSHOT, source_revision=0)
            if room.source_revision != request.expected_revision:
                return SaveSummaryResult(
                    status=SummarySaveStatus.REVISION_CONFLICT,
                    source_revision=room.source_revision,
                )
            new_revision = await ChatRoomRepository(session).save_summary(
                room, request.summary.model_dump(mode="json")
            )
            return SaveSummaryResult(status=SummarySaveStatus.SAVED, source_revision=new_revision)

    async def _get_turn(
        self, turns: ChatTurnStateRepository, room_id: UUID, request_id: str
    ) -> ChatTurnState:
        turn = await turns.get(room_id, request_id)
        if turn is None:
            raise TurnStorageError(f"등록되지 않은 요청입니다: {request_id}")
        return turn
