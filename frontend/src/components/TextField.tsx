/**
 * 라벨 + input + 에러 메시지를 한 덩어리로 묶은 필드.
 *
 * react-hook-form 의 `register(...)` 결과를 그대로 받아 `input` 에 펼친다. 폼 상태를
 * 컴포넌트가 따로 들지 않으므로(비제어) 리렌더가 최소화된다.
 */

import type { InputHTMLAttributes } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

interface TextFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "name" | "id"> {
  /** 필드 식별자. `label` 의 htmlFor 와 input 의 id 를 함께 맞춘다. */
  id: string;
  label: string;
  registration: UseFormRegisterReturn;
  /** 검증 실패 메시지. 있으면 빨간 테두리 + 아래에 문구. */
  error?: string;
}

export function TextField({
  id,
  label,
  registration,
  error,
  ...inputProps
}: TextFieldProps) {
  const describedById = error ? `${id}-error` : undefined;

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedById}
        className={[
          "rounded-md border px-3 py-2 text-sm outline-none transition",
          "focus:ring-2 focus:ring-slate-400",
          error ? "border-red-400 bg-red-50" : "border-slate-300 bg-white",
        ].join(" ")}
        {...inputProps}
        {...registration}
      />
      {error ? (
        <p id={describedById} className="text-xs text-red-600">
          {error}
        </p>
      ) : null}
    </div>
  );
}
