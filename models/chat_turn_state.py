"""턴의 생애주기(시작~확정/실패)와 request_id 재요청 충돌 감지 전용 테이블.

`docs/erd/app.md` "chat_turn_state" 절(2026-09-19 승인)을 그대로 옮긴다. `chat_message` 와 분리한
이유는 턴이 메시지를 만들기 전에 실패하거나 재시도될 수 있고, 그때도 "이 request_id 는 처리 중/실패"
라는 사실을 알아야 하기 때문이다.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


def _sql_enum(enum_cls: type[StrEnum], *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class TurnStateStatus(StrEnum):
    """저장되는 턴 상태. `agent/schemas.py`의 `TurnBeginStatus` 중 저장 상태에 해당하는 값만 둔다.
    `new`(행 없음)와 `conflict`(fingerprint 불일치)는 조회 시점의 판정이라 컬럼에 담지 않는다."""

    IN_PROGRESS = "in_progress"
    STAGED = "staged"
    COMPLETED = "completed"
    FAILED = "failed"


class TurnFailureCode(StrEnum):
    """`agent/schemas.py`의 `TurnFailureCode` 와 값만 맞춰 별도 선언한다."""

    GRAPH = "graph"
    STORAGE = "storage"


class ChatTurnState(EntityBase):
    __tablename__ = "chat_turn_state"
    __table_args__ = (
        UniqueConstraint("chat_room_id", "request_id", name="uq_chat_turn_state_room_request"),
        table_options(comment="채팅 턴의 생애주기와 request_id 재요청 충돌 감지"),
    )

    chat_room_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_room.id", ondelete="CASCADE"),
        nullable=False,
        comment="소속 채팅방. 방이 삭제되면 함께 삭제한다",
    )
    request_id: Mapped[str] = mapped_column(Text, nullable=False, comment="턴 요청 식별자")
    input_fingerprint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="같은 request_id 로 다른 입력이 재요청되면 REQUEST_CONFLICT 판정에 사용",
    )
    status: Mapped[TurnStateStatus] = mapped_column(
        _sql_enum(TurnStateStatus, length=16),
        nullable=False,
        comment="in_progress/staged/completed/failed",
    )
    staged_output: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="ChatTurnOutput 직렬화. complete_turn 전 임시 보관"
    )
    staged_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="SessionSnapshot 직렬화. staged_output 과 같은 시점에 임시 보관",
    )
    failure_code: Mapped[TurnFailureCode | None] = mapped_column(
        _sql_enum(TurnFailureCode, length=16), nullable=True, comment="graph/storage"
    )
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="실패 상세")
    retryable: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="재시도 가능 여부"
    )
