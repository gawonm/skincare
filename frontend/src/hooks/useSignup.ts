/**
 * 회원가입 요청을 다루는 훅.
 *
 * `useLogin` 과 같은 패턴. 백엔드가 가입 성공 시 곧바로 세션 쿠키를 내려주므로,
 * 이 훅의 성공 = 로그인까지 완료된 상태다.
 */

import { useMutation } from "@tanstack/react-query";

import { AuthApi } from "../api/auth";
import type { SignupRequest, UserResponse } from "../api/auth";
import type { ApiError } from "../api/client";

export function useSignup() {
  return useMutation<UserResponse, ApiError, SignupRequest>({
    mutationFn: (body) => AuthApi.signup(body),
  });
}
