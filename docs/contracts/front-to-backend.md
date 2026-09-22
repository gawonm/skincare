# front → backend: 홈 화면

> 상태: **초안**. 프론트는 현재 피그마 화면을 fixture로만 표시한다. 아래 계약이 합의된 뒤
> 백엔드가 구현하고 프론트가 실제 API로 교체한다.

## 범위

- `GET /home`은 로그인 여부에 따라 홈 화면에 필요한 상품 섹션과 CTA를 한 번에 반환한다.
- 로그인 사용자는 `display_mode=personalized`, 비로그인 사용자는 `display_mode=guest`를 반환한다.
- 로그인 상태의 판별은 세션 쿠키로만 한다. 프론트가 사용자 ID를 요청에 넣지 않는다.
- 상품 상세·AI 채팅·마이페이지의 개별 API는 이 계약 범위 밖이다.

## 부르는 대상

- `GET /home`
  - 인증: 선택. 세션 쿠키가 유효하면 개인화 응답을, 없으면 게스트 응답을 반환한다.
  - 응답: 단일 JSON(`application/json`).
  - 타입 소유: 불리는 쪽인 backend가 `backend/schemas/home.py`에 정의한다.

## 출력

```python
from enum import StrEnum

from pydantic import BaseModel


class HomeDisplayMode(StrEnum):
    GUEST = "guest"
    PERSONALIZED = "personalized"


class HomeSectionKind(StrEnum):
    RECOMMENDED = "recommended"
    POPULAR = "popular"


class HomeCtaKind(StrEnum):
    START_CHAT = "start_chat"


class HomeProductCard(BaseModel):
    product_id: str
    brand_name: str
    product_name: str
    thumbnail_url: str | None
    price_label: str | None


class HomeProductSection(BaseModel):
    kind: HomeSectionKind
    title: str
    products: list[HomeProductCard]


class HomeCta(BaseModel):
    kind: HomeCtaKind
    label: str


class HomeResponse(BaseModel):
    display_mode: HomeDisplayMode
    greeting_name: str | None
    sections: list[HomeProductSection]
    cta: HomeCta
```

### 응답 예시

```json
{
  "display_mode": "personalized",
  "greeting_name": "서연",
  "sections": [
    {
      "kind": "recommended",
      "title": "서연님을 위한 추천 제품",
      "products": [
        {
          "product_id": "product-001",
          "brand_name": "브랜드명",
          "product_name": "제품명",
          "thumbnail_url": null,
          "price_label": "24,000원"
        }
      ]
    }
  ],
  "cta": {
    "kind": "start_chat",
    "label": "AI에게 피부 고민 상담하기"
  }
}
```

## 실패했을 때

- 세션이 없거나 만료되어도 `401`을 반환하지 않는다. 게스트 응답을 반환한다.
- 응답을 만들 수 없는 서버 오류는 `500`을 반환한다. 프론트의 오류 화면·재시도 UX는 미정이다.
- 상품이 없을 때 섹션을 빈 배열로 유지할지, 섹션 자체를 제외할지는 미정이다.

## 아직 안 정한 것

임의로 채우지 않는다. 아래 항목은 front·backend·기획이 합의한 뒤 이 문서를 갱신한다.

1. 개인화 추천의 기준: 사용자 피부 프로필, 채팅 이력, 저장 상품 중 무엇을 사용할지.
2. 게스트의 인기 상품 선정 기준과 정렬 기준.
3. 사용자 피부 프로필의 저장 위치와 조회 계약. 새 테이블이나 기존 테이블 변경이 필요하면
   ERD 승인 후 진행한다.
4. CTA가 실제로 호출할 경로. 현재 프론트는 `/chat` 화면 이동만 수행한다.
5. `product_id`의 실제 타입(UUID 또는 다른 식별자)과 `thumbnail_url`의 이미지 제공 방식.
6. 상품이 없거나 추천 계산이 실패한 경우의 섹션 표시 정책.

## 구현 순서

1. 기획·front·backend가 위 미정 항목을 합의한다.
2. DB 구조 변경이 필요하면 `docs/erd/app.md`를 먼저 수정하고 승인받는다.
3. backend가 `backend/schemas/home.py`와 `GET /home`을 구현한다.
4. front가 `HomePage.tsx`의 fixture를 API 응답으로 교체한다.
5. 로그인·게스트 상태에서 화면과 API를 함께 검증한다.

## 관련 문서

- [홈 화면 Frontend ↔ Backend API 계약 초안](https://app.notion.com/p/3e3db8d22c1281b7b2a3fc3609791c36?pvs=204)
- [front → backend: AI 채팅](#front--backend-ai-채팅-로그인-사용자-서버-저장형)

---

# front → backend: AI 채팅 (로그인 사용자, 서버 저장형)

2026-09-19 backend가 수정한 초안이다. 처음 front가 쓴 초안은 "비로그인 일회성, 서버 저장 없음"
이었으나, Agent 담당자 확인(사용자당 방 1개, 화면을 벗어났다 돌아오면 화면은 빈 상태지만
Agent는 이전 대화를 기억)에 따라 서버 저장형으로 바꿨다. 응답 형태는 Agent 구조를 따라 단일
JSON으로 정했다(2026-09-21). 확정 전이며, 아래 "아직 안 정한 것"은 front·agent 담당과 합의한 뒤
채운다. 합의 전에는 이 형태로 구현하지 않는다(CLAUDE.md 규칙 16).

## 범위

- 이번 작업은 `POST /chat` 한 턴(메시지 하나 보내고 답 받기)이다.
- **로그인 사용자 전용**이다. 비로그인(게스트) 채팅은 이번 범위에 없다.
- **서버가 대화를 저장한다.** 사용자당 채팅방은 1개이며, 서버가 세션의 로그인 사용자로 방을
  찾는다(없으면 만든다). 그래서 요청에 방 식별자를 실어 보내지 않는다.
- 화면을 나갔다 다시 들어오면 프론트는 빈 화면에서 시작한다. 그래도 Agent는 이전 대화를
  기억한다. 이전 메시지를 화면에 다시 그려주는 조회 API는 이번 범위 밖이다.
- 저장 테이블(`chat_room`/`chat_message`/`chat_turn_state`)은 data 파트가 만든다.
  [backend-to-data.md](backend-to-data.md), [docs/erd/app.md](../erd/app.md) 참고.

## 부르는 대상

- `POST /chat`
  - 인증: **필수**. 세션 쿠키가 없거나 만료면 `401`. 401을 받은 프론트 화면 처리는 미정이다.
  - 응답: 단일 JSON(`application/json`). 아래 "출력" 절 참고.

## 입력

- 타입 소유: 불리는 쪽이 소유한다 (규칙 11).
  - 백엔드: `backend/schemas/chat.py`
  - 프론트: `frontend/src/schemas/chat.ts` 에 zod 로 미러링만 한다. 원본을 프론트가 갖지 않는다.

```python
class ChatRequest(BaseModel):
    # 클라이언트가 발급한다. 네트워크 재시도로 같은 요청이 다시 와도 같은 턴으로 인식하게
    # 하려는 것이다(멱등성).
    request_id: str
    message: str
    # 이전에 화면에 보여준 후보 목록·루틴을 가리킬 때만 채운다. 채우는 방식은 미정.
    candidate_set_id: str | None = None
    routine_version: int | None = None
```

- 이전 버전 초안의 `messages: list[ChatMessage]`(전체 대화 배열)는 폐기했다. 서버가 대화를
  저장하므로 프론트가 매번 전체를 보낼 필요가 없다.
- `backend/schemas/chat.py`의 `ChatSendMessageRequest`가 위 형태와 같다(방 식별자 없음).

### 예시

```json
{
  "request_id": "b3c1f6e0-...",
  "message": "지성 피부는 레티놀 몇 %부터 시작해?"
}
```

## 출력

Agent는 한 턴이 끝나면 완성된 응답(`ChatTurnOutput`)을 한 번에 돌려주므로, 응답도 그대로 단일
JSON으로 내려준다. 토큰을 조금씩 내보내는 스트리밍 응답은 없다. 타입은 `backend/schemas/chat.py`의
`ChatTurnResponse`가 소유하고, 필드 구성은 Agent의 `ChatTurnOutput`과 같다.

| 필드 | 설명 |
| --- | --- |
| `chat_room_id`, `request_id` | 어느 방의 어느 요청에 대한 응답인지 |
| `assistant_message_id` | 저장된 어시스턴트 메시지 ID |
| `status` | `completed` / `needs_input` / `partial` / `error` |
| `message` | 답변 본문 |
| `intents` | Agent가 해석한 요청 의도 목록 |
| `follow_up_question` | `needs_input`일 때 되묻는 질문 |
| `artifacts` | 후보 상품 목록, 루틴, 근거 답변 등 |
| `citations` | 답변의 근거 인용 |
| `unresolved` | 확정하지 못한 성분·상품 등 |
| `error_code`, `retryable` | 오류일 때 코드와 재시도 가능 여부 |
| `save_handoff` | 루틴 저장 안내 |

## 실패했을 때 (규칙 7)

HTTP 상태 코드는 아래 셋만 쓰고, Agent가 돌려주는 오류는 상태 코드로 바꾸지 않는다(2026-09-21 확정).

- 로그인하지 않았거나 세션 만료: `401`. 프론트는 `/login`으로 보낸다.
- 요청 본문 검증 실패: `422`.
- Agent 오류(남의 방 접근, 같은 `request_id`로 다른 입력, 이미 처리 중, 실행 실패·시간 초과 등):
  **`200`이고 응답 본문의 `status`가 `error`**이며 `error_code`(`room_forbidden`,
  `request_conflict`, `request_in_progress`, `graph_execution_failed` 등)와 `retryable`로 알린다.
  Agent 오류 코드의 의미는 `docs/contracts/backend-to-agent.md` 6절을 따른다.
- 프론트 화면 처리: 오류 메시지(`message`)를 대화창에 보여 주고, `retryable`이 `true`면
  "다시 시도"를 함께 보여 준다. 다시 시도할 때는 같은 `request_id`를 그대로 보낸다(멱등성).
- `503`: 서버에 Agent가 아직 준비되지 않았을 때(배포·기동 중 일시적 상태).

## 아직 안 정한 것

임의로 채우지 않는다 (규칙 3). front·agent 담당과 합의 후 기록한다.

1. `candidate_set_id`/`routine_version`을 프론트가 언제 어떻게 채우는지.
2. "대화 초기화"(에이전트 기억만 새로 시작) 기능이 필요한지. 필요하면 별도 엔드포인트가 필요하다.
3. 화면은 비어 있는데 Agent가 이전 대화를 언급할 때의 사용자 경험(안내 문구 등)은 front·기획이 판단한다.
4. 대화가 길어질 때 자르기: 토큰 예산을 아는 에이전트가 프롬프트 조립 단계에서 처리하는 쪽이 유력.

## 다음 작업 (이번 범위 밖)

- 이전 대화 목록/이력 조회 엔드포인트(화면에 과거 메시지를 다시 보여줄 때).
- 게스트(비로그인) 채팅: front 쪽 논의에서 별도로 다룬다(단기 `sessionStorage`, 장기 Redis 세션).

## 절차 (규칙 16)

1. (폐기) front 가 처음 초안을 작성했다 — 비로그인·무상태 전제, SSE 스트리밍 응답.
2. (완료) backend 가 서버 저장형·사용자당 방 1개 기준으로 이 문서를 수정한다.
3. front·agent 담당에게 변경 내용을 설명하고 "아직 안 정한 것"을 논의해 확정한다.
4. 확정 후 구현한다. 불리는 쪽이 `backend/schemas/chat.py` 와 stub 엔드포인트를 먼저 만들고,
   프론트가 그것으로 붙인다. 채팅 저장 테이블은 data 파트가 먼저 만들어야 한다.
5. front·backend 양쪽 `README.md` "관련 문서" 에 이 파일 링크를 건다.

## 관련 문서

- [backend-to-agent.md](backend-to-agent.md): backend 가 Agent 를 부르는 계약. 방 식별·멱등성·
  실패 계약이 여기서 나온다.
- [backend-to-data.md](backend-to-data.md): 채팅 저장 테이블 생성 요청.
- [docs/erd/app.md](../erd/app.md): `chat_room`/`chat_message`/`chat_turn_state` ERD.

---

# front → backend: 회원가입 확장 (성별·연령대·약관동의)

**확정됨 (2026-09-11).** 호출하는 쪽(front)이 쓴 초안을 backend가 구현까지 마쳤다. 아래
"확정된 내용"이 최종 형태다. front는 `frontend/src/schemas/auth.ts`를 이 문서와 맞춰
갱신하고, `POST /auth/signup` 요청에 새 필드(`gender`/`age_group`/`terms_agreed`)를 실제로
실어 보내도 된다 — 더 이상 email/password/name만 보낼 필요 없다.

## 배경

피그마 회원가입 시안(node `93:25`, 파일 `2C2MK9s2UnKQMC3Hbm9O3X`)에 지금 계약에 없는
입력이 추가됐다.

- 비밀번호 재확인: 서버로 보내지 않는다. 프론트에서 비밀번호와 일치하는지만 확인하는
  순수 클라이언트 검증이라 이 계약에 없다.
- 성별, 연령대, 이용약관 동의: 서버가 저장해야 하는 값이라 계약·스키마·DB 변경이 필요하다.

## 부르는 대상

- `POST /auth/signup` (기존 엔드포인트, 요청 필드만 확장)

## 입력

- 타입 소유: 불리는 쪽(backend)이 소유한다 (규칙 11). 실제 정의는
  `backend/schemas/auth.py`의 `SignupRequest`이고 `Gender`/`AgeGroup`은
  `models/user.py`에 있다(DB 컬럼 타입과 API 입력 타입을 하나로 공유). 아래는 그 형태를
  그대로 옮긴 것이다 — 어긋나면 `backend/schemas/auth.py`가 최신이다.

```python
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator


class Gender(StrEnum):  # models/user.py
    FEMALE = "female"
    MALE = "male"
    UNSPECIFIED = "unspecified"


class AgeGroup(StrEnum):  # models/user.py
    TEENS = "10s"
    TWENTIES = "20s"
    THIRTIES = "30s"
    FORTIES = "40s"
    FIFTIES_PLUS = "50s_plus"


class SignupRequest(BaseModel):  # backend/schemas/auth.py
    email: EmailStr
    password: PasswordStr  # 기존 정의 재사용
    name: NameStr  # 기존 정의 재사용
    gender: Gender
    age_group: AgeGroup
    # Literal[True]라 false나 누락이면 이 필드 자체에서 422가 난다 — 클라이언트 검증을
    # 서버가 못 믿는다는 전제(규칙 7 취지)와, "terms_agreed=false 저장"이 애초에 불가능하다는
    # 걸 타입으로 드러낸다.
    terms_agreed: Literal[True]
```

두 필드 모두 **가입 시 필수**다. 나중에 프로필 화면에서 값을 바꿀 수 있게 할지는 이 계약
범위 밖(그때 별도 `PATCH` 계약이 필요하다).

### 예시

```json
{
  "email": "user@example.com",
  "password": "abcd1234",
  "name": "홍길동",
  "gender": "female",
  "age_group": "20s",
  "terms_agreed": true
}
```

## 출력

`UserResponse`에 `gender`/`age_group`을 포함한다. `terms_agreed`/`terms_agreed_at`은
포함하지 않는다(내부 감사용 데이터라 화면에 노출할 이유가 없다).

```json
{
  "id": "...",
  "email": "user@example.com",
  "name": "홍길동",
  "gender": "female",
  "age_group": "20s",
  "is_active": true,
  "created_at": "..."
}
```

## 실패했을 때 (규칙 7)

- `terms_agreed: false` 또는 누락: `422` (Pydantic 검증 실패로 자연히 발생).
- `gender`/`age_group`에 정의되지 않은 값: `422`.
- 그 외 실패는 기존 계약과 동일 (이메일 중복 `409` 등).

## 확정된 내용 (2026-09-11, backend·사용자 승인 완료)

- **DB 스키마**: 별도 프로필 테이블이 아니라 `app_user`에 컬럼 4개(`gender`, `age_group`,
  `terms_agreed`, `terms_agreed_at`)를 추가했다. 근거는
  [docs/erd/app.md](../erd/app.md)의 `app_user` 절. 마이그레이션:
  `migrations/versions/b518f9fd7cf7_...`.
- **`terms_agreed`**: 값을 저장한다(게이트로만 쓰고 버리지 않음). `terms_agreed_at`에
  동의 시각(서버가 요청을 받은 시각)도 같이 남겨 나중에 분쟁·감사 대응이 가능하게 했다.
- **필수 여부**: 가입 시 필수. 프로필에서 나중에 채우는 흐름은 없다.
- **응답 포함**: `gender`/`age_group`은 `UserResponse`에 포함, `terms_agreed*`는 미포함.

## 절차 (규칙 16)

1. (완료) front 가 이 초안을 작성한다.
2. (완료) backend 담당에게 설명하고 합의했다.
3. (완료) "아직 안 정한 것"을 확정했다 — 위 "확정된 내용" 참고. ERD 문서 승인 완료.
4. (완료, backend) `backend/schemas/auth.py`·`models/user.py`·마이그레이션 구현 및 검증.
5. (완료, front) `frontend/src/api/auth.ts`·`frontend/src/pages/SignupPage.tsx`를
   이 문서에 맞춰 갱신해 `gender`/`age_group`/`terms_agreed`를 `POST /auth/signup`에
   실어 보내도록 연결했다(`passwordConfirm`은 여전히 서버로 보내지 않는다 — 클라이언트
   전용 검증). 로컬에서 회원가입·로그인 전체 플로우로 연동 검증 완료.

## 관련 문서

- 피그마: `성분노트 MVP 와이어프레임` 파일, node `93:25` ("Overview / 회원가입")
- 기존 계약(회원가입 email/password/name)의 실제 정의: `backend/schemas/auth.py`
