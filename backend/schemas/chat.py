"""AI 채팅 HTTP API 요청/응답 모델 (로그인 사용자 전용).

방 접근 권한(`actor_id`)은 세션에서 얻으므로 요청 본문에 넣지 않는다
(`backend/api/dependencies.py`의 `CurrentUserDep`과 같은 패턴). 게스트(비로그인) 채팅은
이번 범위에 없다.

`agent/schemas.py`의 `ChatServiceRequest`/`ChatTurnOutput`을 그대로 복제하지 않는다.
그 타입은 agent가 소유한 backend→agent 계약이라 backend가 사본을 만들면 두 정의가
갈라진다(CLAUDE.md 규칙 16). 대신 여기서는 HTTP 바디에만 필요한 요청/응답 봉투만 새로
정의하고, 중첩 타입(`Citation`·`UnresolvedItem`·`Artifact`·`RoutineSaveHandoff`)은 agent
것을 그대로 가져다 쓴다.

주의: 이 응답 모델은 아직 front와 합의되지 않은 초안이다
(`docs/contracts/backend-to-agent.md` 7절 "ChatTurnOutput을 외부 HTTP 응답으로 노출할
backend→front 계약" — 미합의 항목으로 명시돼 있다). 실제 엔드포인트에 연결하기 전에
front와 형태를 맞춰야 한다(규칙 16).
"""

from pydantic import BaseModel, Field

from agent.schemas import (
    Artifact,
    ChatStatus,
    Citation,
    ErrorCode,
    Intent,
    RoutineSaveHandoff,
    UnresolvedItem,
)


class ChatSendMessageRequest(BaseModel):
    """방 하나에 메시지 한 턴을 보낸다."""

    chat_room_id: str = Field(min_length=1)
    # 클라이언트가 네트워크 재시도로 같은 요청을 다시 보내도 같은 턴으로 인식되도록
    # (`REQUEST_CONFLICT`/`REQUEST_IN_PROGRESS`, backend-to-agent.md 6절) 서버가 아니라
    # 클라이언트가 발급해 보낸다.
    request_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    candidate_set_id: str | None = None
    routine_version: int | None = Field(default=None, ge=1)


class ChatTurnResponse(BaseModel):
    """`ChatTurnOutput`을 HTTP 응답으로 옮긴 것. 필드 구성은 agent 쪽과 동일하다."""

    chat_room_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    assistant_message_id: str = Field(min_length=1)
    status: ChatStatus
    message: str = Field(min_length=1)
    intents: list[Intent] = Field(default_factory=list)
    follow_up_question: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
    error_code: ErrorCode | None = None
    retryable: bool = False
    save_handoff: RoutineSaveHandoff | None = None
