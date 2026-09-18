# backend → data: 채팅 히스토리 테이블 생성 요청

backend가 `agent/ports.py`의 `ChatHistoryRepository` 포트를 구현하려면 로그인 사용자의
채팅방·메시지·턴 상태를 저장할 테이블 3개가 필요하다. `models/`, `migrations/`는
[CLAUDE.md](../../CLAUDE.md) 규칙 15의 경로표상 data 파트 소유라 backend가 직접 만들지
않는다. 아래 스키마는 사용자 승인을 받은 ERD([docs/erd/app.md](../erd/app.md) "로그인
사용자 채팅 히스토리" 절)를 그대로 옮긴 것이며, ERD와 이 문서가 어긋나면 ERD가 최신이다.

## 요청 대상

`models/chat_room.py`, `models/chat_message.py`, `models/chat_turn_state.py` 3개 파일과
그에 대응하는 Alembic migration.

작성 후 `config.yaml`의 `database.model_modules`에 세 모듈 경로 추가 필요(규칙 13) —
빠뜨리면 Alembic autogenerate가 세 테이블을 인식하지 못한다.

## 스키마

### `chat_room`

```python
class ChatRoom(EntityBase):
    __tablename__ = "chat_room"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(Uuid, unique=True, nullable=False, default=uuid4)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_completed_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    task_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pending_question: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    candidate_set: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    routine: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

키: PK `id`(`EntityBase`), FK `user_id` → `app_user.id` (`ON DELETE CASCADE`), UK `thread_id`.

### `chat_message`

```python
class ChatMessage(EntityBase):
    __tablename__ = "chat_message"
    __table_args__ = (
        UniqueConstraint("chat_room_id", "sequence"),
        UniqueConstraint("chat_room_id", "request_id", "role"),
    )

    chat_room_id: Mapped[UUID] = mapped_column(ForeignKey("chat_room.id", ondelete="CASCADE"), nullable=False)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[MessageRole] = mapped_column(_sql_enum(MessageRole, length=16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
```

`MessageRole`은 `agent/schemas.py`의 `MessageRole`(`user`/`assistant`)과 값을 맞춰 `models/`에
별도 재선언한다(규칙 11 — `models/`가 `agent/`를 import하지 않음, `models/claim_document.py`의
`ClaimDatasetSplit`과 같은 관례).

키: PK `id`, FK `chat_room_id`(CASCADE), UK `(chat_room_id, sequence)`,
UK `(chat_room_id, request_id, role)`.

### `chat_turn_state`

```python
class ChatTurnState(EntityBase):
    __tablename__ = "chat_turn_state"
    __table_args__ = (UniqueConstraint("chat_room_id", "request_id"),)

    chat_room_id: Mapped[UUID] = mapped_column(ForeignKey("chat_room.id", ondelete="CASCADE"), nullable=False)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TurnStateStatus] = mapped_column(_sql_enum(TurnStateStatus, length=16), nullable=False)
    staged_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    staged_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[TurnFailureCode | None] = mapped_column(_sql_enum(TurnFailureCode, length=16), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

`TurnStateStatus`(`in_progress`/`staged`/`completed`/`failed`)와 `TurnFailureCode`
(`graph`/`storage`)도 `agent/schemas.py`의 `TurnBeginStatus`/`TurnFailureCode` 값에 맞춰
`models/`에 재선언한다. `TurnBeginStatus`의 `new`/`conflict` 값은 저장 상태가 아니라
조회 시점의 판정 결과라 컬럼에는 담지 않는다(`new`=행 없음, `conflict`=`input_fingerprint`
불일치로 조회 시점에 계산).

키: PK `id`, FK `chat_room_id`(CASCADE), UK `(chat_room_id, request_id)`.

## 누가 이 타입을 소유하나

`models/chat_room.py`, `models/chat_message.py`, `models/chat_turn_state.py` — data 파트.
이 세 SQLAlchemy 모델을 실제로 조회·저장하는 `backend/repositories/`,
`backend/services/`(`ChatHistoryRepository` 포트 구현)는 backend 파트가 이어서 작성한다.

## 실패했을 때

테이블 생성 자체에는 실패 계약이 없다(CRUD 로직이 아니라 스키마 정의). 다만 아래는
DB 제약으로 반드시 강제해야 한다 — 애플리케이션 계층에서만 걸러내면 동시 요청 시 조용히
깨진다.

- `chat_message`의 두 UNIQUE 제약(멱등성·페이징 보장)
- `chat_turn_state`의 `(chat_room_id, request_id)` UNIQUE(재요청 충돌 감지)
- 모든 FK `ON DELETE CASCADE`(계정 삭제 시 대화도 함께 삭제)

## 아직 안 정한 것

임의로 채우지 않는다(규칙 3). 확인 후 이 문서와 ERD를 함께 갱신한다.

- LangGraph 체크포인터를 별도 Postgres 체크포인터 라이브러리로 운영할지, 위 JSONB
  스냅샷(`chat_room`의 `profile`/`candidate_set`/... 컬럼)으로 대신할지. 후자라면 별도
  체크포인터 테이블은 만들지 않는다.
- 사용자가 이전 채팅방 목록을 조회하는 API/화면 필요 여부(front 요구사항 미정) — 필요하면
  `chat_room`에 표시용 제목 컬럼이 추가로 필요할 수 있다.
- 방 삭제·보관(soft delete) 정책.

## 절차

1. (완료) ERD 초안 작성 및 사용자 확인 — [docs/erd/app.md](../erd/app.md).
2. (완료) backend가 이 계약 문서 초안 작성.
3. data 파트 담당자 확인.
4. 확정 후 data 파트가 `models/` 3개 파일 + migration 작성, `config.yaml`
   `model_modules` 갱신.
5. backend가 `ChatHistoryRepository` 실제 구현으로 이어감.

## 관련 문서

- [docs/erd/app.md](../erd/app.md) — 컬럼 표·mermaid ERD·설계 근거 원본
- [docs/contracts/backend-to-agent.md](backend-to-agent.md) — `ChatHistoryRepository` 포트 계약
- `agent/schemas.py`, `agent/ports.py` — 옮겨온 원 계약
