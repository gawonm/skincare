# 웹 채팅 실제 서비스 연동 현황 및 인계 항목

> 작성일: 2026-09-22
>
> 상태: **Frontend·Backend 단일 JSON 연결 완료 / Agent 운영 조립 대기**
>
> 다른 작업자가 동일한 Frontend·Backend 연동을 진행 중일 수 있으므로 담당 브랜치와 계약을
> 확인하기 전에는 이 문서를 근거로 API나 화면 코드를 새로 만들지 않는다.

## 목적

현재 저장소의 웹 채팅 화면과 실제 Agent 실행 경로 사이에 남아 있는 연결 작업을 기록한다.
이 문서는 구현 소유권을 가져오지 않으며, 병렬 작업과 중복 구현을 피하기 위한 점검표다.

## 현재 확인된 상태

- Frontend `useChat`은 `api/chat.ts`의 `ChatApi.sendMessage`로 실제 `POST /chat`을 호출한다.
- 응답 계약은 SSE가 아니라 완성된 단일 JSON이며, Frontend Zod 스키마와 Backend Pydantic
  스키마가 구현돼 있다.
- Backend에는 `/chat` 라우터, 채팅방 준비, 턴 저장, 히스토리 저장소가 연결돼 있다.
- Backend `main.py`는 인증 라우터와 채팅 라우터를 정적 파일 마운트보다 먼저 등록한다.
- `get_agent_chat_service`는 `app.state.agent_chat_service`가 없으면 503을 반환한다.
- Backend lifespan은 아직 `ProductionAgentFactory`와 `ChatService`를 조립해 위 상태값에 넣지 않는다.
- 실제 DB·OpenAI·BGE-M3·BGE reranker를 연결한 전체 흐름은 진단 CLI에서만 확인된다.
- 진단 CLI의 히스토리·체크포인터·루틴 저장소는 개발용 메모리 구현이다.

## 기존 계약

현재 단일 JSON 계약은 [front-to-backend.md](../contracts/front-to-backend.md)의
`front → backend: AI 채팅` 절에 있다. 남은 연결 작업은 다음 항목을 기준으로 담당자 합의가
필요하다.

- 운영 lifespan에서 사용할 Agent 저장소·체크포인터·LLM 조립 방식
- Client 취소 시 이미 시작된 Agent 실행과 턴 저장 상태를 어떻게 처리할지
- `artifacts`, `citations`, `partial`, `unresolved`의 화면 표시 방식
- 새 대화 초기화와 같은 방의 동시 요청 처리 방식

## 필요한 연결 순서

```text
Frontend ChatRequest
→ Backend POST /chat
→ ChatTurnService가 로그인 사용자의 방을 준비
→ API 요청을 Agent ChatServiceRequest로 변환하고 턴 상태를 저장
→ ChatService.handle_turn
→ ChatTurnOutput을 단일 JSON 응답으로 변환
→ Frontend Zod 파서
→ ChatMessageList 렌더링
```

## 담당자 확인 체크리스트

- [x] Frontend가 목 스트림 대신 실제 `POST /chat` 단일 JSON API를 호출한다.
- [x] Backend가 `/chat` 라우터와 채팅방·턴·히스토리 서비스를 제공한다.
- [x] 라우터를 정적 파일 `/` 마운트보다 먼저 등록한다.
- [ ] 실제 Agent 운영 조립 작업 중인 브랜치와 담당자를 확인한다.
- [ ] Backend가 Agent 입출력 타입의 복사본을 만들지 않고 명시적 변환 경계를 최종 확인한다.
- [ ] 앱 lifespan에서 운영 DB 저장소·체크포인터·상품 taxonomy를 주입한다.
- [ ] 사용자 취소, 타임아웃, 부분 응답, 재시도 동작을 통합 테스트한다.
- [ ] Claim UUID·Evidence UUID 같은 내부 식별자가 화면 본문에 노출되지 않는지 확인한다.
- [ ] 개발 서버와 배포된 단일 오리진 환경을 모두 검증한다.

## 완료 조건

- 브라우저 요청이 실제 `ChatService.handle_turn`까지 도달한다.
- 실제 응답이 목 데이터 없이 단일 JSON으로 화면에 표시된다.
- 로그인 사용자 기준으로 합의된 방·히스토리 계약이 동작한다.
- Agent 오류가 정상 답변 문구로 위장되지 않고 계약의 오류 응답으로 전달된다.
- 기존 인증 API와 SPA 정적 파일 라우팅이 깨지지 않는다.

## 이번 작업에서 하지 않는 것

- Agent `ChatService`의 운영 lifespan 조립
- `artifacts`·`citations`·부분 응답의 화면 구현
- 새 DB 테이블 또는 migration 작성
- Docker·Compose·배포 설정 변경
