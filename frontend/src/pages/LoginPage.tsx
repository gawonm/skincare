/**
 * 로그인 화면(피그마 node 93:2).
 *
 * zod 로 형식을 먼저 막고, 통과하면 `useLogin` 으로 `POST /auth/login` 을 보낸다.
 * 성공하면 홈(`/home`)으로 이동한다. 뒤로가기로 로그인 화면에 다시 오지 않도록
 * `replace` 로 히스토리를 덮는다.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";

import { AuthLayout } from "../components/AuthLayout";
import { FormAlert } from "../components/FormAlert";
import { SubmitButton } from "../components/SubmitButton";
import { TextField } from "../components/TextField";
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
    <AuthLayout>
      <div className="flex flex-1 flex-col gap-3">
        <div className="flex items-center gap-1.5 self-start rounded-full bg-moss-tint px-3 py-1.5">
          <span className="size-2 rounded-full bg-moss-deep" />
          <span className="text-[13px] font-bold text-moss-deep">성분노트</span>
        </div>

        <h1 className="text-[28px] font-bold leading-[1.45] text-ink">
          내 피부를 위한
          <br />
          성분 루틴을 시작해요
        </h1>
        <p className="text-sm text-ink-soft">근거 있는 성분 정보와 나만의 스킨케어 스케줄</p>

        <div className="h-2.5" />

        <form onSubmit={onSubmit} className="flex flex-col gap-3" noValidate>
          {login.isError ? (
            <FormAlert tone="error" message={login.error.message} />
          ) : null}

          <TextField
            id="email"
            label="이메일"
            type="email"
            autoComplete="email"
            placeholder="name@example.com"
            registration={register("email")}
            error={errors.email?.message}
          />
          <TextField
            id="password"
            label="비밀번호"
            type="password"
            autoComplete="current-password"
            placeholder="8자 이상 입력"
            registration={register("password")}
            error={errors.password?.message}
          />

          {/* 비밀번호 재설정 플로우는 이번 범위 밖이라 링크가 아닌 텍스트로만 둔다. */}
          <span className="self-end text-xs font-medium text-blue-point">
            비밀번호를 잊으셨나요?
          </span>

          <SubmitButton pending={login.isPending} pendingLabel="로그인 중...">
            로그인
          </SubmitButton>

          <p className="text-center text-[13px] font-medium text-blue-point">
            처음이신가요? <Link to="/signup">회원가입</Link>
          </p>
        </form>
      </div>
    </AuthLayout>
  );
}
