"""`chat_turn_state` 조회/저장. SQL은 이 계층에만 둔다. commit은 하지 않는다."""

from datetime import timedelta
from typing import ClassVar
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.chat_turn_state import ChatTurnState, TurnFailureCode, TurnStateStatus


class ChatTurnStateRepository:
    """턴 하나의 생애주기(진행 중, 임시 저장, 확정, 실패) 저장소."""

    _ACTIVE_STATUSES: ClassVar[tuple[TurnStateStatus, ...]] = (
        TurnStateStatus.IN_PROGRESS,
        TurnStateStatus.STAGED,
    )
    _EXPIRED_IN_PROGRESS_DETAIL: ClassVar[str] = (
        "처리 중이던 요청이 제한 시간 안에 끝나지 않아 실패로 처리했습니다."
    )
    _EXPIRED_STAGED_DETAIL: ClassVar[str] = (
        "임시 저장된 결과가 제한 시간 안에 확정되지 않아 실패로 처리했습니다."
    )

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, room_id: UUID, request_id: str) -> ChatTurnState | None:
        result = await self._session.execute(
            select(ChatTurnState).where(
                ChatTurnState.chat_room_id == room_id, ChatTurnState.request_id == request_id
            )
        )
        return result.scalar_one_or_none()

    async def has_active_other(self, room_id: UUID, exclude_request_id: str | None) -> bool:
        """다른 요청이 이 방에서 진행 중이거나 확정 대기 중인지."""
        conditions = [
            ChatTurnState.chat_room_id == room_id,
            ChatTurnState.status.in_(self._ACTIVE_STATUSES),
        ]
        if exclude_request_id is not None:
            conditions.append(ChatTurnState.request_id != exclude_request_id)
        result = await self._session.execute(select(ChatTurnState.id).where(*conditions).limit(1))
        return result.first() is not None

    async def expire_stale(self, room_id: UUID, stale_after: timedelta) -> None:
        """오래 갱신되지 않은 진행 중/임시 저장 턴을 실패로 바꾼다.

        서버가 턴 도중 죽으면 그 방이 영원히 "처리 중"으로 막힌다. 시간 비교는 DB 시계(`now()`)로
        해서 앱 서버와 DB 사이의 시각 차이가 판정에 끼지 않게 한다.
        """
        deadline = func.now() - stale_after
        for status, code, detail in (
            (TurnStateStatus.IN_PROGRESS, TurnFailureCode.GRAPH, self._EXPIRED_IN_PROGRESS_DETAIL),
            (TurnStateStatus.STAGED, TurnFailureCode.STORAGE, self._EXPIRED_STAGED_DETAIL),
        ):
            await self._session.execute(
                update(ChatTurnState)
                .where(
                    ChatTurnState.chat_room_id == room_id,
                    ChatTurnState.status == status,
                    ChatTurnState.updated_at < deadline,
                )
                .values(
                    status=TurnStateStatus.FAILED,
                    failure_code=code,
                    failure_detail=detail,
                    retryable=True,
                )
                # 세션이 이미 읽어 둔 턴 객체도 함께 갱신한다. `expire_all`은 비동기 세션에서
                # 나중에 속성을 읽을 때 예기치 않은 DB 접근을 일으켜 쓰지 않는다.
                .execution_options(synchronize_session="fetch")
            )

    async def create(self, room_id: UUID, request_id: str, input_fingerprint: str) -> ChatTurnState:
        turn = ChatTurnState(
            chat_room_id=room_id,
            request_id=request_id,
            input_fingerprint=input_fingerprint,
            status=TurnStateStatus.IN_PROGRESS,
        )
        self._session.add(turn)
        await self._session.flush()
        return turn

    async def mark_in_progress(self, turn: ChatTurnState) -> None:
        """실패한 턴을 재시도할 때 실패 정보를 지우고 다시 진행 중으로 돌린다."""
        turn.status = TurnStateStatus.IN_PROGRESS
        turn.failure_code = None
        turn.failure_detail = None
        turn.retryable = None
        await self._session.flush()

    async def stage(
        self,
        turn: ChatTurnState,
        output: dict[str, JsonValue],
        snapshot: dict[str, JsonValue],
    ) -> None:
        turn.staged_output = output
        turn.staged_snapshot = snapshot
        turn.status = TurnStateStatus.STAGED
        await self._session.flush()

    async def complete(
        self,
        turn: ChatTurnState,
        output: dict[str, JsonValue],
        snapshot: dict[str, JsonValue],
    ) -> None:
        """확정한 뒤에도 출력과 스냅샷을 지우지 않는다.

        같은 `request_id` 재요청에 저장된 응답을 그대로 돌려주고, 과거 후보 목록·루틴 버전을
        아티팩트 ID로 다시 찾으려면 남아 있어야 한다. `chat_room`에는 최신 값 하나만 있다.
        """
        turn.staged_output = output
        turn.staged_snapshot = snapshot
        turn.status = TurnStateStatus.COMPLETED
        turn.failure_code = None
        turn.failure_detail = None
        turn.retryable = None
        await self._session.flush()

    async def mark_failed(
        self, turn: ChatTurnState, code: TurnFailureCode, detail: str, retryable: bool
    ) -> None:
        turn.status = TurnStateStatus.FAILED
        turn.failure_code = code
        turn.failure_detail = detail
        turn.retryable = retryable
        await self._session.flush()

    async def find_completed_with_artifact(
        self,
        room_id: UUID,
        *,
        candidate_set_id: str | None,
        routine_id: str | None,
        routine_version: int | None,
    ) -> list[ChatTurnState]:
        """확정된 턴 중 요청한 후보 목록 또는 루틴을 아티팩트로 가진 턴을 오래된 순으로 찾는다."""
        artifacts = ChatTurnState.staged_output["artifacts"]
        conditions = []
        if candidate_set_id is not None:
            conditions.append(artifacts.contains([{"candidate_set_id": candidate_set_id}]))
        if routine_id is not None:
            routine_match: dict[str, JsonValue] = {"routine_id": routine_id}
            if routine_version is not None:
                routine_match["version"] = routine_version
            conditions.append(artifacts.contains([routine_match]))
        if not conditions:
            return []
        result = await self._session.execute(
            select(ChatTurnState)
            .where(
                ChatTurnState.chat_room_id == room_id,
                ChatTurnState.status == TurnStateStatus.COMPLETED,
                or_(*conditions),
            )
            .order_by(ChatTurnState.created_at)
        )
        return list(result.scalars().all())
