/**
 * 로그인 화면.
 *
 * zod 로 형식을 먼저 막고, 통과하면 `useLogin` 으로 `POST /auth/login` 을 보낸다.
 * 범위가 "화면 2개"라서 성공 후 이동할 홈이 아직 없다. 그래서 이동 대신 성공 배너만
 * 띄운다(계획서의 '임의로 정한 것' 1번).
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { FormAlert } from "../components/FormAlert";
import { SubmitButton } from "../components/SubmitButton";
import { TextField } from "../components/TextField";
import { AuthLayout } from "../components/AuthLayout";
import { useLogin } from "../hooks/useLogin";
import { loginSchema } from "../schemas/auth";
import type { LoginFormValues } from "../schemas/auth";

export function LoginPage() {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });
  const login = useLogin();

  const onSubmit = handleSubmit((values) => {
    login.mutate(values);
  });

  return (
    <AuthLayout
      title="로그인"
      subtitle="이메일과 비밀번호를 입력해 주세요."
      footer={
        <>
          계정이 없으신가요?{" "}
          <Link to="/signup" className="font-medium text-slate-900 underline">
            회원가입
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {login.isSuccess ? (
          <FormAlert tone="success" message="로그인되었습니다." />
        ) : null}
        {login.isError ? (
          <FormAlert tone="error" message={login.error.message} />
        ) : null}

        <TextField
          id="email"
          label="이메일"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          registration={register("email")}
          error={errors.email?.message}
        />
        <TextField
          id="password"
          label="비밀번호"
          type="password"
          autoComplete="current-password"
          registration={register("password")}
          error={errors.password?.message}
        />

        <SubmitButton pending={login.isPending} pendingLabel="로그인 중...">
          로그인
        </SubmitButton>
      </form>
    </AuthLayout>
  );
}
