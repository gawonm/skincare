/**
 * 회원가입 화면(피그마 node 93:25)의 성별 선택 버튼 그룹.
 *
 * `docs/contracts/front-to-backend.md` "회원가입 확장" 절이 아직 backend 와 합의 전이라,
 * 이 값은 화면 상태로만 쓰이고 `POST /auth/signup` 에는 실리지 않는다.
 */

import { Gender } from "../constants/auth";

const GENDER_LABEL: Record<Gender, string> = {
  [Gender.Female]: "여성",
  [Gender.Male]: "남성",
  [Gender.Unspecified]: "선택 안 함",
};

const GENDER_OPTIONS = [Gender.Female, Gender.Male, Gender.Unspecified] as const;

interface GenderSelectProps {
  value: Gender | undefined;
  onChange: (value: Gender) => void;
  error?: string;
}

export function GenderSelect({ value, onChange, error }: GenderSelectProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium text-ink">성별</span>
      <div className="flex gap-1.5" role="radiogroup" aria-label="성별">
        {GENDER_OPTIONS.map((option) => {
          const selected = option === value;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(option)}
              className={[
                "rounded-full border border-solid px-3.5 py-2 text-[11px]",
                selected
                  ? "border-moss-deep bg-moss-tint font-bold text-moss-deep"
                  : "border-hairline bg-surface font-normal text-ink-soft",
              ].join(" ")}
            >
              {GENDER_LABEL[option]}
            </button>
          );
        })}
      </div>
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </div>
  );
}
