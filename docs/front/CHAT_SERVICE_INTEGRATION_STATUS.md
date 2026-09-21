# 웹 채팅 실제 서비스 연동 현황 및 인계 항목

> 작성일: 2026-09-22
>
> 상태: **문서화만 완료 / 구현하지 않음**
>
> 다른 작업자가 동일한 Frontend·Backend 연동을 진행 중일 수 있으므로 담당 브랜치와 계약을
> 확인하기 전에는 이 문서를 근거로 API나 화면 코드를 새로 만들지 않는다.

## 목적

현재 저장소의 웹 채팅 화면과 실제 Agent 실행 경로 사이에 남아 있는 연결 작업을 기록한다.
이 문서는 구현 소유권을 가져오지 않으며, 병렬 작업과 중복 구현을 피하기 위한 점검표다.

## 현재 확인된 상태

- Frontend `useChat`은 `api/chatMock.ts`의 `streamMockChatResponse`를 호출한다.
- Frontend에는 실제 `/chat` SSE 요청·파서 구현이 없다.
- Backend에는 `/chat` 라우터와 `backend/schemas/chat.py`가 없다.
- Backend `main.py`는 현재 인증 라우터만 등록한다.
- Backend lifespan은 `ProductionAgentFactory`와 `ChatService`를 조립하지 않는다.
- 실제 DB·OpenAI·BGE-M3·BGE reranker를 연결한 전체 흐름은 진단 CLI에서만 확인된다.
- 진단 CLI의 히스토리·체크포인터·루틴 저장소는 개발용 메모리 구현이다.

## 기존 계약

기본 HTTP/SSE 초안은 [front-to-backend.md](../contracts/front-to-backend.md)의
`front → backend: AI 채팅` 절에 있다. 아직 다음 항목이 미정이므로 구현 전에 담당자 합의가
필요하다.

- 비로그인 일회성 대화와 Agent의 방·권한 기반 `ChatServiceRequest`를 어떻게 연결할지
- SSE `stage`, `token`, `warning`, `sources`, `done`, `error`의 최종 payload
- Client 전체 메시지 배열과 Agent 서버 히스토리 중 어느 쪽을 기준 상태로 사용할지
- 스트림 취소 시 Agent 실행 취소와 턴 저장 상태를 어떻게 처리할지
- Citation 상세 필드와 사용자에게 노출할 출처 링크 범위

## 필요한 연결 순서

```text
Frontend ChatRequest
→ Backend POST /chat
→ API 요청을 Agent ChatServiceRequest로 변환
→ ChatService.handle_turn
→ ChatTurnOutput을 SSE 이벤트로 변환
→ Frontend SSE 파서
→ ChatMessageList 렌더링
```

## 담당자 확인 체크리스트

- [ ] 실제 작업 중인 브랜치와 담당자를 확인했다.
- [ ] `front-to-backend.md`의 미정 항목을 Frontend·Backend·Agent 담당자가 확정했다.
- [ ] Backend가 Agent 입출력 타입의 복사본을 만들지 않고 명시적 변환 경계를 정했다.
- [ ] 앱 lifespan에서 운영 DB 저장소·체크포인터·상품 taxonomy를 주입한다.
- [ ] 라우터를 정적 파일 `/` 마운트보다 먼저 등록한다.
- [ ] Frontend가 목 스트림 import를 실제 API 모듈로 교체한다.
- [ ] 사용자 취소, 타임아웃, 부분 응답, 재시도 동작을 통합 테스트한다.
- [ ] Claim UUID·Evidence UUID 같은 내부 식별자가 화면 본문에 노출되지 않는지 확인한다.
- [ ] 개발 서버와 배포된 단일 오리진 환경을 모두 검증한다.

## 완료 조건

- 브라우저 요청이 실제 `ChatService.handle_turn`까지 도달한다.
- 실제 응답이 목 데이터 없이 화면에 스트리밍된다.
- 인증 유무와 관계없이 합의된 계약대로 동작한다.
- Agent 오류가 정상 답변 문구로 위장되지 않고 합의된 `error` 이벤트로 전달된다.
- 기존 인증 API와 SPA 정적 파일 라우팅이 깨지지 않는다.

## 이번 작업에서 하지 않는 것

- `/chat` API 구현
- Frontend SSE client 구현
- 운영 히스토리·체크포인터 저장소 구현
- 새 DB 테이블 또는 migration 작성
- Docker·Compose·배포 설정 변경
