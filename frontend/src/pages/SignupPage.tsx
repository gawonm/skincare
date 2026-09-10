/**
 * 회원가입 화면.
 *
 * 백엔드가 가입 성공 시 곧바로 로그인 처리(세션 쿠키 발급)하므로, 성공 = 로그인 완료다.
 * 이메일 중복(409)은 상단 배너뿐 아니라 이메일 필드 밑에도 표시해 어디를 고쳐야 하는지
 * 바로 보이게 한다.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { FormAlert } from "../components/FormAlert";
import { SubmitButton } from "../components/SubmitButton";
import { TextField } from "../components/TextField";
import { AuthLayout } from "../components/AuthLayout";
import { AUTH_ERROR_MESSAGE, AuthHttpStatus } from "../constants/auth";
import { useSignup } from "../hooks/useSignup";
import { signupSchema } from "../schemas/auth";
import type { SignupFormValues } from "../schemas/auth";

export function SignupPage() {
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<SignupFormValues>({ resolver: zodResolver(signupSchema) });
  const signup = useSignup();

  const onSubmit = handleSubmit((values) => {
    signup.mutate(values, {
      onError: (error) => {
        // 중복 이메일은 사용자가 이메일만 바꾸면 되는 상황이라 필드 레벨로도 안내한다.
        if (error.status === AuthHttpStatus.Conflict) {
          setError("email", {
            message: AUTH_ERROR_MESSAGE[AuthHttpStatus.Conflict],
          });
        }
      },
    });
  });

  return (
    <AuthLayout
      title="회원가입"
      subtitle="이메일, 비밀번호, 이름을 입력해 주세요."
      footer={
        <>
          이미 계정이 있으신가요?{" "}
          <Link to="/login" className="font-medium text-slate-900 underline">
            로그인
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {signup.isSuccess ? (
          <FormAlert
            tone="success"
            message={`${signup.data.name}님, 가입이 완료되었습니다.`}
          />
        ) : null}
        {signup.isError ? (
          <FormAlert tone="error" message={signup.error.message} />
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
          autoComplete="new-password"
          registration={register("password")}
          error={errors.password?.message}
        />
        <TextField
          id="name"
          label="이름"
          type="text"
          autoComplete="name"
          registration={register("name")}
          error={errors.name?.message}
        />

        <SubmitButton pending={signup.isPending} pendingLabel="가입 중...">
          회원가입
        </SubmitButton>
      </form>
    </AuthLayout>
  );
}
