# 백엔드 (FastAPI · 업무 로직)

`backend/api/`, `backend/schemas/`, `backend/services/`, `backend/repositories/`,
`backend/main.py` 를 다룬다. 폴더 구조와 의존 방향은 [STRUCTURE.md](../../STRUCTURE.md),
코드 작성 규칙은 [CLAUDE.md](../../CLAUDE.md)를 따른다.

작업을 시작하기 전에 이 문서를 먼저 읽는다. 여기 적힌 담당 범위 밖은 구현하지 않는다
(CLAUDE.md 규칙 15).

## 담당 범위

- HTTP 엔드포인트 (`backend/api/`)
- 요청/응답 Pydantic 스키마 (`backend/schemas/`)
- 업무 로직과 트랜잭션 (`backend/services/`)
- DB 조회/저장 쿼리 (`backend/repositories/`)
- 앱 생성과 lifespan (`backend/main.py`)
- 인증·인가 (로그인, 회원가입, 세션, 토큰)
- **추천 엔진** — 점수 계산, 필터링
- **제품 랭킹** — 정렬, 가격 기반 비교
- **스케줄링(루틴) 엔진** — 사용 순서·주기 규칙
- agent 호출 (`services/` 에서만)

다음은 담당 범위 밖이다. 여기 손대지 않는다.

- RAG 파이프라인, 챗봇 응답 생성, 의도 분류 (agent 파트)
- 추천 근거 문장 생성 등 LLM 을 쓰는 부분 (agent 파트)
- 화면 구현 (front 파트)
- 데이터 수집·정제·적재 스크립트, `models/` 신규 테이블 설계 (data 파트)

**결정론적 로직이 이 파트다.** 점수를 매기고 정렬하고 거르는 계산은 여기서 하고,
LLM 이 필요한 순간에만 `services/` 에서 agent 를 호출한다. 경계가 애매하면 임의로 정하지 말고
사용자에게 묻는다 (CLAUDE.md 규칙 3).

## 지켜야 할 제약

- import 방향: `api` → `services` → `repositories` → `models`, 그리고 `services` → `agent`.
  반대 방향으로 import 하지 않는다.
- SQLAlchemy 쿼리(`select`, `insert` 등)는 `repositories/` 에만 쓴다. `api/`, `services/`
  에서는 쓰지 않는다 (CLAUDE.md 규칙 12).
- `commit` 은 `services/` 에서만 한다. 리포지토리는 조회와 저장만 한다.
- 테이블 하나당 리포지토리 클래스 하나. 세션은 생성자에서 주입받는다.
- 요청/응답 모델은 `schemas/` 에 두고, `models/` 의 SQLAlchemy 객체를 그대로 응답하지 않는다.
- 모든 코드는 클래스 기반으로 작성한다 (CLAUDE.md 규칙 1).

## 테이블을 새로 만들어야 할 때

추천·랭킹에 새 테이블이 필요하면 직접 만들지 않는다. ERD 문서를 먼저 쓰고 사용자 확인을 받는다
(CLAUDE.md 규칙 14). 경로는 `docs/erd/<db이름>.md`.

## 산출물

front 파트가 호출하는 HTTP API 와 그 요청/응답 스키마. 엔드포인트 경로나 응답 형태를 바꿀 때는
front 담당자에게 먼저 알린다.

## 현재 상태

| 기능 | 상태 | 파일 |
| --- | --- | --- |
| 회원가입 | 구현됨 | `backend/api/auth.py`, `backend/services/auth.py` |
| 로그인·로그아웃 | 구현됨 | 위와 같음 |
| 내 정보 조회 | 구현됨 | 위와 같음 |
| 세션 저장소 | 구현됨 | `backend/repositories/session.py` |
| 추천 엔진 | 미구현 | — |
| 제품 랭킹 | 미구현 | — |
| 스케줄링(루틴) 엔진 | 미구현 | — |

## 관련 문서

- RAG·챗봇 계약(호출할 클래스와 스키마)은 [docs/agent/README.md](../agent/README.md).
- 화면이 기대하는 응답 형태는 [docs/front/README.md](../front/README.md).
- 데이터 적재 현황은 [docs/data/README.md](../data/README.md).
- 폴더 구조와 import 방향은 [STRUCTURE.md](../../STRUCTURE.md).
- 설치·실행 명령과 마이그레이션 절차는 [SETUP.md](../../SETUP.md).
