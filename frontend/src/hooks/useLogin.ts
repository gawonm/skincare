/**
 * 로그인 요청을 다루는 훅.
 *
 * TanStack Query 의 `useMutation` 으로 감싸서 진행중(`isPending`)·실패(`error`)·성공
 * 상태를 페이지가 직접 관리하지 않게 한다. 실패 시 `error` 는 `ApiError` 다.
 */

import { useMutation } from "@tanstack/react-query";

import { AuthApi } from "../api/auth";
import type { LoginRequest, UserResponse } from "../api/auth";
import type { ApiError } from "../api/client";

export function useLogin() {
  return useMutation<UserResponse, ApiError, LoginRequest>({
    mutationFn: (body) => AuthApi.login(body),
  });
}
