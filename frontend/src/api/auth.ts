/**
 * `/auth` 요청 함수와 그 입출력 타입.
 *
 * 타입은 `backend/schemas/auth.py` 와 1:1 로 맞춘다. 백엔드가 필드를 바꾸면 여기도
 * 같이 바꿔야 하며, 그 전까지는 컴파일이 통과해도 런타임에서 어긋난다.
 */

import { AuthEndpoint } from "../constants/auth";
import { fetchJson } from "./client";

/** `POST /auth/login` 요청 body. */
export interface LoginRequest {
  email: string;
  password: string;
}

/** `POST /auth/signup` 요청 body. */
export interface SignupRequest {
  email: string;
  password: string;
  name: string;
}

/** `/auth/*` 성공 응답(`UserResponse`). `id`·`created_at` 은 문자열로 직렬화되어 온다. */
export interface UserResponse {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  created_at: string;
}

export class AuthApi {
  /** 이메일/비밀번호로 로그인. 성공 시 세션 쿠키가 응답에 실려 온다. */
  static login(body: LoginRequest): Promise<UserResponse> {
    return fetchJson<UserResponse>(AuthEndpoint.Login, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  /** 회원가입. 백엔드가 성공 시 곧바로 로그인 처리하여 세션 쿠키를 함께 내려준다. */
  static signup(body: SignupRequest): Promise<UserResponse> {
    return fetchJson<UserResponse>(AuthEndpoint.Signup, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }
}
