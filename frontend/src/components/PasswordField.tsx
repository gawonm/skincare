/**
 * 보기 토글이 붙은 비밀번호 필드(회원가입 화면, 피그마 node 93:25).
 *
 * 로그인 화면은 토글이 없는 일반 `TextField` 를 그대로 쓴다. 여기서만 필요해서
 * `TextField` 자체를 토글 로직으로 무겁게 만들지 않고 얇게 감쌌다.
 */

import { useState } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { TextField } from "./TextField";

interface PasswordFieldProps {
  id: string;
  label: string;
  autoComplete: string;
  registration: UseFormRegisterReturn;
  error?: string;
}

export function PasswordField({ id, label, autoComplete, registration, error }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <TextField
      id={id}
      label={label}
      type={visible ? "text" : "password"}
      autoComplete={autoComplete}
      placeholder="8자 이상 입력"
      compact
      registration={registration}
      error={error}
      trailing={
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          className="shrink-0 text-[10px] font-medium text-moss-deep"
        >
          {visible ? "숨기기" : "보기"}
        </button>
      }
    />
  );
}
