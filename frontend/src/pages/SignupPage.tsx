/**
 * 회원가입 화면(피그마 node 93:25).
 *
 * 백엔드가 가입 성공 시 곧바로 로그인 처리(세션 쿠키 발급)하므로, 성공 = 로그인 완료다.
 * 이메일 중복(409)은 상단 배너뿐 아니라 이메일 필드 밑에도 표시해 어디를 고쳐야 하는지
 * 바로 보이게 한다.
 *
 * 시안에는 비밀번호 재확인·성별·연령대·이용약관 동의가 있지만, `docs/contracts/front-to-backend.md`
 * "회원가입 확장" 절이 아직 backend 와 합의 전이다(규칙 16). 그래서 화면 검증·상태는
 * `signupSchema` 가 전부 다루되, 실제로 `POST /auth/signup` 에는 지금 계약대로
 * email·password·name 만 골라 보낸다.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { AgeSegmentedControl } from "../components/AgeSegmentedControl";
import { AuthLayout } from "../components/AuthLayout";
import { FormAlert } from "../components/FormAlert";
import { GenderSelect } from "../components/GenderSelect";
import { PasswordField } from "../components/PasswordField";
import { SubmitButton } from "../components/SubmitButton";
import { TextField } from "../components/TextField";
import { AUTH_ERROR_MESSAGE, AuthHttpStatus } from "../constants/auth";
import { useSignup } from "../hooks/useSignup";
import { signupSchema } from "../schemas/auth";
import type { SignupFormValues } from "../schemas/auth";

export function SignupPage() {
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<SignupFormValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: { termsAgreed: false },
  });
  const signup = useSignup();

  const onSubmit = handleSubmit((values) => {
    // TODO(contract): gender/ageGroup/termsAgreed 는 합의 전이라 아직 안 보낸다.
    signup.mutate(
      { email: values.email, password: values.password, name: values.name },
      {
        onError: (error) => {
          // 중복 이메일은 사용자가 이메일만 바꾸면 되는 상황이라 필드 레벨로도 안내한다.
          if (error.status === AuthHttpStatus.Conflict) {
            setError("email", {
              message: AUTH_ERROR_MESSAGE[AuthHttpStatus.Conflict],
            });
          }
        },
      },
    );
  });

  return (
    <AuthLayout>
      <div className="flex flex-col gap-2">
        <h1 className="text-[27px] font-bold leading-[1.4] text-ink">회원가입</h1>
        <p className="text-[13px] text-ink-soft">기본 정보를 입력하면 바로 시작할 수 있어요.</p>

        <form onSubmit={onSubmit} className="mt-1 flex flex-col gap-2" noValidate>
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
            id="name"
            label="이름"
            type="text"
            autoComplete="name"
            placeholder="이름을 입력하세요"
            compact
            registration={register("name")}
            error={errors.name?.message}
          />
          <TextField
            id="email"
            label="이메일"
            type="email"
            autoComplete="email"
            placeholder="name@example.com"
            compact
            registration={register("email")}
            error={errors.email?.message}
          />
          <PasswordField
            id="password"
            label="비밀번호"
            autoComplete="new-password"
            registration={register("password")}
            error={errors.password?.message}
          />
          <PasswordField
            id="passwordConfirm"
            label="비밀번호 재확인"
            autoComplete="new-password"
            registration={register("passwordConfirm")}
            error={errors.passwordConfirm?.message}
          />

          <Controller
            control={control}
            name="gender"
            render={({ field }) => (
              <GenderSelect
                value={field.value}
                onChange={field.onChange}
                error={errors.gender?.message}
              />
            )}
          />
          <Controller
            control={control}
            name="ageGroup"
            render={({ field }) => (
              <AgeSegmentedControl
                value={field.value}
                onChange={field.onChange}
                error={errors.ageGroup?.message}
              />
            )}
          />

          <label className="flex items-center gap-2 text-[10px] text-ink-soft">
            <input
              type="checkbox"
              className="size-[18px] shrink-0 rounded-[5px] border border-hairline accent-moss-deep"
              {...register("termsAgreed")}
            />
            이용약관 및 개인정보 처리방침에 동의합니다.
          </label>
          {errors.termsAgreed ? (
            <p className="text-xs text-red-600">{errors.termsAgreed.message}</p>
          ) : null}

          <div className="h-px w-full bg-hairline" />

          <SubmitButton pending={signup.isPending} pendingLabel="가입 중...">
            회원가입
          </SubmitButton>

          <p className="text-center text-[13px] font-medium text-ink-soft">
            이미 계정이 있으신가요?{" "}
            <Link to="/login" className="text-blue-point">
              로그인
            </Link>
          </p>
        </form>
      </div>
    </AuthLayout>
  );
}
