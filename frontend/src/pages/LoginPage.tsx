/**
 * 로그인 화면.
 *
 * zod 로 형식을 먼저 막고, 통과하면 `useLogin` 으로 `POST /auth/login` 을 보낸다.
 * 성공하면 홈(`/home`)으로 이동한다. 뒤로가기로 로그인 화면에 다시 오지 않도록
 * `replace` 로 히스토리를 덮는다.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";

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
  const navigate = useNavigate();

  const onSubmit = handleSubmit((values) => {
    login.mutate(values, {
      onSuccess: () => navigate("/home", { replace: true }),
    });
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
