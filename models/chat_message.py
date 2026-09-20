"""채팅방 안의 메시지 한 건.

`docs/erd/app.md` "chat_message" 절(2026-09-19 승인)을 그대로 옮긴다. 메시지는 수정하지 않아
`updated_at` 은 쓰이지 않지만 ERD 가 다른 테이블과 같은 기본 틀(`EntityBase`)을 유지하도록 정했다.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


def _sql_enum(enum_cls: type[StrEnum], *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class MessageRole(StrEnum):
    """`agent/schemas.py`의 `MessageRole` 과 값만 맞춰 별도 선언한다. `models/` 는 `agent/` 를
    import 하지 않는다(import 방향 규칙)."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(EntityBase):
    __tablename__ = "chat_message"
    __table_args__ = (
        # 방 내 순번 중복 방지 겸 페이징용 인덱스
        UniqueConstraint("chat_room_id", "sequence", name="uq_chat_message_room_sequence"),
        # 같은 턴이 같은 role 메시지를 두 번 만들지 못하게 막아 멱등성을 보조한다
        UniqueConstraint(
            "chat_room_id", "request_id", "role", name="uq_chat_message_room_request_role"
        ),
        table_options(comment="채팅방 안의 메시지 한 건"),
    )

    chat_room_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_room.id", ondelete="CASCADE"),
        nullable=False,
        comment="소속 채팅방. 방이 삭제되면 함께 삭제한다",
    )
    request_id: Mapped[str] = mapped_column(
        Text, nullable=False, comment="이 메시지를 만든 턴의 request_id"
    )
    role: Mapped[MessageRole] = mapped_column(
        _sql_enum(MessageRole, length=16), nullable=False, comment="user/assistant"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="본문")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="방 내 순번. 1부터 증가")
