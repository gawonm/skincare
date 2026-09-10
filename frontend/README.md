# frontend

로그인·회원가입 화면. 백엔드 `/auth` 엔드포인트에 붙는다.

## 스택

| 항목 | 선택 |
| --- | --- |
| 빌드 | Vite + TypeScript |
| UI | React 19 |
| 스타일 | Tailwind CSS v4 (`@tailwindcss/vite`, 설정 파일 없음) |
| 라우팅 | react-router-dom |
| 서버 상태 | @tanstack/react-query |
| 폼·검증 | react-hook-form + zod |

통신 방식은 일반 요청(REST/JSON)이다. LLM 스트리밍(SSE)은 이 화면 범위 밖이다.

## 폴더

```
src/
├── main.tsx          진입점 (QueryClientProvider + RouterProvider)
├── router.tsx        라우트 (/ → /login, /login, /signup)
├── constants/        엔드포인트 경로, 입력 제한, 에러 문구
├── api/              fetch 래퍼(client.ts), /auth 요청 함수(auth.ts)
├── schemas/          zod 스키마 (백엔드 제약 미러링)
├── hooks/            useLogin, useSignup (useMutation 래퍼)
├── pages/            LoginPage, SignupPage
└── components/       AuthLayout, TextField, SubmitButton, FormAlert
```

## 실행

백엔드가 `http://localhost:8000` 에서 떠 있어야 한다. 프론트의 `/auth/*` 요청은
Vite 개발 프록시가 그쪽으로 넘긴다(`vite.config.ts`). 백엔드에 CORS 설정이 없어서
크로스 오리진 대신 same-origin 프록시로 우회하는 구조다.

```bash
# 백엔드 (프로젝트 루트에서, 터미널 A)
just up
just server

# 프론트엔드 (터미널 B)
cd frontend
npm install        # 최초 1회
npm run dev        # http://localhost:5173
```

`http://localhost:5173` 에 접속하면 `/login` 으로 이동한다.

## 빌드 / 타입 검사

```bash
npm run build      # tsc -b + vite build
```

## 범위 밖 (다음 작업)

로그인 상태 유지(`GET /auth/me`), 로그아웃 버튼, 보호 라우트, 로그인 후 홈 화면.
세션 쿠키는 `HttpOnly` 라 JS 로 읽을 수 없고, 로그인 여부는 `/auth/me` 응답으로 판단한다.
