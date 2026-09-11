/**
 * 라벨 + input + 에러 메시지를 한 덩어리로 묶은 필드.
 *
 * react-hook-form 의 `register(...)` 결과를 그대로 받아 `input` 에 펼친다. 폼 상태를
 * 컴포넌트가 따로 들지 않으므로(비제어) 리렌더가 최소화된다.
 *
 * `compact` 는 회원가입 화면(피그마 node 93:25)처럼 필드가 많아 촘촘하게 배치해야
 * 할 때 쓴다. 로그인 화면(93:2)은 기본값을 그대로 쓴다.
 */

import type { InputHTMLAttributes, ReactNode } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

interface TextFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "name" | "id"> {
  /** 필드 식별자. `label` 의 htmlFor 와 input 의 id 를 함께 맞춘다. */
  id: string;
  label: string;
  registration: UseFormRegisterReturn;
  /** 검증 실패 메시지. 있으면 빨간 테두리 + 아래에 문구. */
  error?: string;
  compact?: boolean;
  /** 입력창 오른쪽 안쪽에 붙는 요소(예: 비밀번호 보기 토글 버튼). */
  trailing?: ReactNode;
}

export function TextField({
  id,
  label,
  registration,
  error,
  compact = false,
  trailing,
  ...inputProps
}: TextFieldProps) {
  const describedById = error ? `${id}-error` : undefined;

  return (
    <div className={compact ? "flex flex-col gap-1" : "flex flex-col gap-1.5"}>
      <label
        htmlFor={id}
        className={[
          "font-medium text-ink",
          compact ? "text-[11px]" : "text-xs",
        ].join(" ")}
      >
        {label}
      </label>
      <div
        className={[
          "flex items-center justify-between border border-solid bg-surface-2",
          error ? "border-red-400 bg-red-50" : "border-hairline",
          compact ? "h-[42px] rounded-[11px] px-[13px]" : "h-[46px] rounded-xl px-3.5",
        ].join(" ")}
      >
        <input
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedById}
          className={[
            "w-full bg-transparent text-ink outline-none placeholder:text-ink-soft",
            compact ? "text-xs" : "text-[13px]",
          ].join(" ")}
          {...inputProps}
          {...registration}
        />
        {trailing}
      </div>
      {error ? (
        <p id={describedById} className="text-xs text-red-600">
          {error}
        </p>
      ) : null}
    </div>
  );
}
