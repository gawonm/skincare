"""AI 채팅 HTTP API 요청/응답 모델 (로그인 사용자 전용).

방 접근 권한(`actor_id`)은 세션에서 얻으므로 요청 본문에 넣지 않는다
(`backend/api/dependencies.py`의 `CurrentUserDep`과 같은 패턴). 채팅방도 사용자당 1개라
서버가 로그인 사용자로 방을 찾으므로 요청 본문에 방 식별자를 받지 않는다. 게스트(비로그인)
채팅은 이번 범위에 없다.

`agent/schemas.py`의 `ChatServiceRequest`/`ChatTurnOutput`을 그대로 복제하지 않는다.
그 타입은 agent가 소유한 backend→agent 계약이라 backend가 사본을 만들면 두 정의가
갈라진다(CLAUDE.md 규칙 16). 대신 여기서는 HTTP 바디에만 필요한 요청/응답 봉투만 새로
정의하고, 중첩 타입(`Citation`·`UnresolvedItem`·`Artifact`·`RoutineSaveHandoff`)은 agent
것을 그대로 가져다 쓴다.

`ChatTurnResponse`의 기존 필드(`message`/`artifacts`/`citations`/`unresolved` 등)는
`docs/contracts/front-to-backend.md` "출력" 절대로 합의·구현된 현행 계약이라 그대로 둔다.
`sections`는 같은 문서의 "응답 확장: 섹션" 절에서 **추가만** 한 필드다 — `ChatSectionBuilder`
(`backend/services/chat_response_builder.py`)가 `message`를 문단으로 나눠 구조화 데이터와
대조한 결과이며, agent 코드 변경 없이 backend·front 만으로 만든다.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agent.rag.schemas import DayPeriod, EvidenceSourceType, Weekday
from agent.schemas import (
    Artifact,
    ChatStatus,
    Citation,
    ErrorCode,
    Intent,
    RoutineSaveHandoff,
    UnresolvedItem,
    UnresolvedKind,
)
from models.product import ProductServiceCategory


class ChatSendMessageRequest(BaseModel):
    """로그인 사용자의 채팅방에 메시지 한 턴을 보낸다."""

    # 클라이언트가 네트워크 재시도로 같은 요청을 다시 보내도 같은 턴으로 인식되도록
    # (`REQUEST_CONFLICT`/`REQUEST_IN_PROGRESS`, backend-to-agent.md 6절) 서버가 아니라
    # 클라이언트가 발급해 보낸다.
    request_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    candidate_set_id: str | None = None
    routine_version: int | None = Field(default=None, ge=1)


class ChatSectionType(StrEnum):
    """`message` 문단 하나가 어떤 방식으로 그려지는지. `ChatSectionParser`가 정한다."""

    TEXT = "text"
    PRODUCT_LIST = "product_list"
    ROUTINE = "routine"
    EVIDENCE = "evidence"
    NOTICE = "notice"


class ChatTextSection(BaseModel):
    """구조화 데이터와 대조되지 않은 문단. 정보 손실 없이 그대로 글로 보여 준다."""

    type: Literal[ChatSectionType.TEXT] = ChatSectionType.TEXT
    text: str = Field(min_length=1)


class ProductCardView(BaseModel):
    """상품 후보 카드 한 장. `ProductCandidate` + `product` 테이블 보강값."""

    rank: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    # 아래 넷은 product 테이블에서 보강한다. product_id 가 UUID 가 아니거나(개발용 fixture)
    # 테이블에 없으면 None 이다 — 실패해도 카드 자체는 그대로 낸다.
    brand: str | None = None
    image_url: str | None = None
    lowest_price: int | None = None
    service_category: ProductServiceCategory | None = None
    reasons: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    basis_label: str | None = None


class ProductGroupView(BaseModel):
    """루틴 역할별 상품 묶음. `role_label`이 없으면 역할 구분 없는 단일 묶음이다."""

    role_label: str | None = None
    items: list[ProductCardView] = Field(min_length=1)


class ChatProductListSection(BaseModel):
    type: Literal[ChatSectionType.PRODUCT_LIST] = ChatSectionType.PRODUCT_LIST
    candidate_set_id: str = Field(min_length=1)
    groups: list[ProductGroupView] = Field(min_length=1)
    text: str = Field(min_length=1)


class RoutineStepView(BaseModel):
    period: DayPeriod
    order: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RoutineDayView(BaseModel):
    weekday: Weekday
    steps: list[RoutineStepView] = Field(min_length=1)


class ChatRoutineSection(BaseModel):
    type: Literal[ChatSectionType.ROUTINE] = ChatSectionType.ROUTINE
    routine_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    days: list[RoutineDayView] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


class ReferenceView(BaseModel):
    source_title: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    url: str | None = None
    source_type: EvidenceSourceType


class ChatEvidenceSection(BaseModel):
    type: Literal[ChatSectionType.EVIDENCE] = ChatSectionType.EVIDENCE
    answer_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    text: str = Field(min_length=1)
    references: list[ReferenceView] = Field(default_factory=list)


class ChatNoticeSection(BaseModel):
    type: Literal[ChatSectionType.NOTICE] = ChatSectionType.NOTICE
    kind: UnresolvedKind
    detail: str = Field(min_length=1)
    retryable: bool = False


ChatSection = Annotated[
    ChatTextSection
    | ChatProductListSection
    | ChatRoutineSection
    | ChatEvidenceSection
    | ChatNoticeSection,
    Field(discriminator="type"),
]


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
    # message 를 문단 순서대로 나눈 것. ChatTurnOutput.message 가 항상 1자 이상이라 항상
    # 1개 이상이다(docs/contracts/front-to-backend.md "응답 확장: 섹션").
    sections: list[ChatSection] = Field(min_length=1)
