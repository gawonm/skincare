# front → backend: AI 채팅 (비로그인 일회성, 서버 저장 없음)

호출하는 쪽(front)이 쓴 초안이다. 확정 전이며, 아래 "아직 안 정한 것" 은 backend·agent
담당과 합의한 뒤 채운다. 합의 전에는 이 형태로 구현하지 않는다 (CLAUDE.md 규칙 16).

## 범위

- 이번 작업은 `POST /chat` 하나다.
- 대화 이력은 프론트 화면 컴포넌트의 메모리(상태 배열)에만 있다. 서버·에이전트는 무상태다.
- 화면을 나가면 프론트가 그 배열을 버리는 것이 곧 "초기화"다.
- 로그인 사용자도 지금은 대화를 저장하지 않는다. 이름 인사(`GET /auth/me`)만 다르다.
- 로그인 사용자 대화 저장은 이 계약 범위 밖이다. 아래 "다음 작업" 참고.

## 부르는 대상

- `POST /chat`
  - 응답: `text/event-stream` (SSE). 스트리밍 중 클라이언트가 연결을 끊어 취소할 수 있다.
  - 인증: 선택. 세션 쿠키가 있으면 실어 보내되, 없어도 200 으로 동작한다.

## 입력

- 타입 소유: 불리는 쪽이 소유한다 (규칙 11).
  - 백엔드: `backend/schemas/chat.py`
  - 프론트: `frontend/src/schemas/chat.ts` 에 zod 로 미러링만 한다. 원본을 프론트가 갖지 않는다.

```python
from enum import StrEnum

from pydantic import BaseModel


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: Role
    content: str


class ChatRequest(BaseModel):
    # 현재 화면 세션의 전체 대화. 마지막 원소가 방금 보낸 사용자 메시지다.
    # 서버는 이 배열을 저장하지 않고, 에이전트 프롬프트 조립에만 쓴다.
    messages: list[ChatMessage]
```

### 예시

```json
{
  "messages": [
    { "role": "user", "content": "비타민C랑 레티놀 같이 써도 돼?" },
    { "role": "assistant", "content": "같이 사용할 수 있지만 시간대를 나눠 쓰는 걸 권장해요. ..." },
    { "role": "user", "content": "지성 피부는 레티놀 몇 %부터 시작해?" }
  ]
}
```

## 출력 — SSE 이벤트

시안 04B(대화 중)·04C(응답 중) 기준. `event` 이름은 아래로 하되 각 `data` 의 정확한
형태는 미정이다.

```
event: stage    data: {"label": "입력하신 요청을 확인하고 있어요"}
event: token    data: {"text": "같이 "}
event: warning  data: {"text": "동시에 바르면 자극이 커질 수 있어요."}
event: sources  data: {"items": [{"label": "성분 DB", "count": 1}, {"label": "피부과 임상 가이드", "count": 2}]}
event: done     data: {}
event: error    data: {"detail": "..."}
```

- `stage`: 응답 생성 전/중의 진행 상태 문구. 0회 이상.
- `token`: 답변 본문 조각. 프론트가 순서대로 이어 붙인다.
- `warning`: 답변에 딸리는 주의 문구(시안 04B의 붉은 박스). 0회 이상.
- `sources`: 근거 출처 요약(시안 04B의 "출처 ·" 줄).
- `done`: 정상 종료. 이 뒤로 이벤트 없음.
- `error`: 실패로 종료. 이 뒤로 이벤트 없음.

## 실패했을 때 (규칙 7)

- 에이전트 타임아웃·오류: `event: error` 를 보내고 스트림을 닫는다. 프론트 UI 처리는 미정.
- 요청 본문 검증 실패: SSE 시작 전 `422` 로 응답한다.

## 아직 안 정한 것

임의로 채우지 않는다 (규칙 3). backend·agent 담당과 합의 후 기록한다.

- `sources` 객체 형태: 라벨 + 건수로 충분한지, 성분노트로 가는 링크나 id 가 필요한지.
- 경고 전달 방식: 별도 `warning` 이벤트로 줄지, `token` 본문 안에 마크업으로 섞을지.
- 에러가 났을 때 프론트 화면 상태: 재시도 버튼, 부분 답변 유지 여부 등. 시안 없음.
- 대화가 길어질 때 자르기: 토큰 예산을 아는 에이전트가 프롬프트 조립 단계에서 처리하는 쪽이 유력.
- `stage` 문구를 서버가 정해 보낼지, 코드값만 보내고 프론트가 문구를 갖고 있을지.

## 다음 작업 (이번 범위 밖)

- 로그인 사용자 대화 서버 저장: `conversation_id`, 대화 목록/이력 조회 엔드포인트,
  대화·메시지 저장 테이블. 새 테이블이므로 먼저 ERD 문서(규칙 14)와 저장 테이블 소유
  파트(backend / data) 합의가 필요하다.

## 절차 (규칙 16)

1. (완료) front 가 이 초안을 작성한다.
2. backend·agent 담당에게 설명한다. 넘길 값의 형태와, 상대 파트에 요청하는 것(SSE 엔드포인트,
   에이전트가 낼 수 있는 이벤트 종류)을 공유한다.
3. "아직 안 정한 것" 을 논의해 확정한다.
4. 확정 후 구현한다. 불리는 쪽이 `backend/schemas/chat.py` 와 stub 엔드포인트를 먼저 만들고,
   프론트가 그것으로 붙인다.
5. front·backend 양쪽 `README.md` "관련 문서" 에 이 파일 링크를 건다.

## 관련 문서

- `docs/contracts/backend-to-agent.md` (backend 가 초안, 아직 없음): 이 계약의 SSE 이벤트는
  에이전트가 낼 수 있는 것에서 나온다. backend 는 이 문서를 확정하기 전에 그쪽과 맞춰야 한다.
