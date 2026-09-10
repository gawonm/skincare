# 프론트엔드 (화면)

`frontend/` 를 다룬다. Vite + React + TypeScript + Tailwind 구성이다. 폴더 구조와 의존 방향은
[STRUCTURE.md](../../STRUCTURE.md), 코드 작성 규칙은 [CLAUDE.md](../../CLAUDE.md)를 따른다.

작업을 시작하기 전에 이 문서를 먼저 읽는다. 여기 적힌 담당 범위 밖은 구현하지 않는다
(CLAUDE.md 규칙 15).

## 담당 범위

- 페이지 (`frontend/src/pages/`)
- 공용 컴포넌트 (`frontend/src/components/`)
- 라우팅 (`frontend/src/router.tsx`)
- 백엔드 API 호출 계층 (`frontend/src/api/`)
- 요청/응답 zod 스키마 (`frontend/src/schemas/`)
- 데이터 패칭·뮤테이션 훅 (`frontend/src/hooks/`)
- 화면 상수 (`frontend/src/constants/`)
- 스타일링, 반응형, 로딩·에러 상태 표시

다음은 담당 범위 밖이다. 여기 손대지 않는다.

- FastAPI 엔드포인트, 응답 형태 변경 (backend 파트)
- 추천 점수·랭킹·스케줄링 로직 (backend 파트)
- RAG·챗봇 (agent 파트)
- 데이터 수집·정제 (data 파트)
- 파이썬 코드 전반

**화면에서 계산하지 않는다.** 추천 순위나 점수를 프론트에서 다시 매기지 않고, 백엔드가 준 순서
그대로 그린다. 필요한 값이 응답에 없으면 직접 만들지 말고 backend 담당자에게 요청한다.

## 지켜야 할 제약

- 백엔드 응답은 zod 스키마로 파싱한 뒤 쓴다. 파싱 없이 `any` 로 흘리지 않는다.
- API 호출은 `src/api/` 의 fetch 래퍼를 통해서만 한다. 컴포넌트에서 `fetch` 를 직접 부르지 않는다.
- 엔드포인트 경로·에러 코드 같은 문자열은 `src/constants/` 에 상수로 뺀다. 컴포넌트 안에
  리터럴로 박지 않는다 (CLAUDE.md 규칙 9).
- 백엔드 응답 형태가 바뀌면 `src/schemas/` 를 먼저 고치고, 그다음 화면을 고친다.
- 새 npm 패키지를 넣기 전에 먼저 물어본다 (CLAUDE.md 규칙 6).

## 입력으로 받는 것

backend 파트가 제공하는 HTTP API. 스펙은 [docs/backend/README.md](../backend/README.md) 의
"현재 상태" 표를 기준으로 하고, 아직 미구현인 API 는 화면도 만들지 않는다. 필요하면 사용자에게
먼저 묻는다 (CLAUDE.md 규칙 3).

## 현재 상태

| 화면 | 상태 | 파일 |
| --- | --- | --- |
| 로그인 | 구현됨 | `src/pages/LoginPage.tsx`, `src/hooks/useLogin.ts` |
| 회원가입 | 구현됨 | `src/pages/SignupPage.tsx`, `src/hooks/useSignup.ts` |
| 추천 결과 화면 | 미구현 | — |
| 챗봇 화면 | 미구현 | — |
| 루틴·스케줄 화면 | 미구현 | — |

공용 컴포넌트는 `AuthLayout`, `FormAlert`, `SubmitButton`, `TextField` 가 있다.

## 관련 문서

- 호출할 API 와 응답 스키마는 [docs/backend/README.md](../backend/README.md).
- 챗봇 응답 형태는 [docs/agent/README.md](../agent/README.md).
- 폴더 구조와 의존 방향은 [STRUCTURE.md](../../STRUCTURE.md).
- 설치·실행 명령은 [SETUP.md](../../SETUP.md).
