/**
 * 앱 진입점.
 *
 * TanStack Query(서버 상태)와 React Router(화면 전환)를 앱 최상단에 한 번만 건다.
 * `QueryClient` 는 모듈 스코프에서 한 번 만들어, 리렌더마다 새로 생기지 않게 한다.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import { router } from "./router";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    // 로그인/회원가입은 사용자가 누를 때만 보내야 한다. 자동 재시도로 같은 요청이
    // 여러 번 나가면 계정 상태를 오해하기 쉬우므로 mutation 재시도를 끈다.
    mutations: { retry: false },
  },
});

const rootElement = document.getElementById("root");
if (rootElement === null) {
  // index.html 의 마운트 지점이 사라진 상황. 조용히 넘어가면 빈 화면만 남으므로 즉시 알린다.
  throw new Error("루트 엘리먼트(#root)를 찾을 수 없습니다. index.html 을 확인해 주세요.");
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
