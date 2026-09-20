"""로그인 사용자의 채팅방(사용자당 1개).

`docs/erd/app.md` "chat_room" 절(2026-09-19 승인)을 그대로 옮긴다. 방의 세션 상태(`profile`,
`task_context`, `candidate_set` 등)는 Agent 가 소유한 DTO 를 그대로 왕복 저장하는 세션 캐시라 JSONB
로 두었고, Backend 가 내부 필드로 검색하지 않는다. 게스트(비로그인) 저장은 이번 범위에 없다.
"""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


class ChatRoom(EntityBase):
    __tablename__ = "chat_room"
    __table_args__ = (
        # 사용자당 방 1개. UNIQUE 가 없으면 동시 요청이나 버그로 방이 둘 생겨도 DB 가 막지 못한다
        UniqueConstraint("user_id", name="uq_chat_room_user_id"),
        UniqueConstraint("thread_id", name="uq_chat_room_thread_id"),
        table_options(
            comment="로그인 사용자의 채팅방. 사용자당 1개이며 Agent 세션 스냅샷을 담는다"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        comment="방 소유 사용자. 계정 삭제 시 대화도 함께 삭제한다. 로그인 사용자 전용이라 NULL 없음",
    )
    thread_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        comment="LangGraph 체크포인터 네임스페이스(AuthorizedRoom.thread_id)",
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
        comment="SessionSnapshot.schema_version 그대로 저장",
    )
    source_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="낙관적 잠금 카운터. 턴이 커밋될 때마다 +1, SaveSummaryRequest.expected_revision 과 비교",
    )
    last_completed_request_id: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="멱등성 확인용. 마지막으로 완전히 커밋된 턴의 request_id"
    )
    profile: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="UserProfile 직렬화",
    )
    task_context: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="TaskContext 직렬화",
    )
    pending_question: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="PendingQuestion 직렬화"
    )
    candidate_set: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="ProductCandidateSet 직렬화. 가장 최근 것 하나만"
    )
    routine: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="RoutinePlan 직렬화. 가장 최근 것 하나만"
    )
    evidence: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment="EvidenceRecord 목록 직렬화",
    )
    summary: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="ConversationSummary 직렬화"
    )
