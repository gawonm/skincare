/**
 * 라우트 정의.
 *
 * 이번 범위의 화면은 로그인·회원가입 둘뿐이다. 진입 시 갈 곳이 명확하도록 "/" 는
 * "/login" 으로 보낸다. 로그인 후 홈/보호 라우트는 다음 작업(계획서 '범위 밖').
 */

import { createBrowserRouter, Navigate } from "react-router-dom";

import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";

export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/login" replace /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/signup", element: <SignupPage /> },
  // 정의되지 않은 경로도 로그인으로 되돌린다.
  { path: "*", element: <Navigate to="/login" replace /> },
]);
