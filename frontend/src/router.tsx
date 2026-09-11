/**
 * 라우트 정의.
 *
 * 로그인·회원가입에 더해, 로그인 성공 후 이동할 홈 화면(`/home`)을 둔다. `/home` 은
 * 아직 보호 라우트가 아니다(세션 검사 없이 열린다). 세션 기반 접근 제어는 다음 작업.
 * `/chat` 은 AI 채팅 화면(현재 목 데이터). 진입 시 갈 곳이 명확하도록 "/" 는 "/login" 으로 보낸다.
 */

import { createBrowserRouter, Navigate } from "react-router-dom";

import { ChatRoute } from "./constants/chat";
import { ChatPage } from "./pages/ChatPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";

export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/login" replace /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/signup", element: <SignupPage /> },
  { path: "/home", element: <HomePage /> },
  { path: ChatRoute.Chat, element: <ChatPage /> },
  // 정의되지 않은 경로도 로그인으로 되돌린다.
  { path: "*", element: <Navigate to="/login" replace /> },
]);
