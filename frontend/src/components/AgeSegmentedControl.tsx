/**
 * 회원가입 화면(피그마 node 93:25)의 연령대 세그먼트 컨트롤.
 *
 * `docs/contracts/front-to-backend.md` "회원가입 확장" 절이 아직 backend 와 합의 전이라,
 * 이 값은 화면 상태로만 쓰이고 `POST /auth/signup` 에는 실리지 않는다.
 */

import { AgeGroup } from "../constants/auth";

const AGE_GROUP_LABEL: Record<AgeGroup, string> = {
  [AgeGroup.Teens]: "10대",
  [AgeGroup.Twenties]: "20대",
  [AgeGroup.Thirties]: "30대",
  [AgeGroup.Forties]: "40대",
  [AgeGroup.FiftiesPlus]: "50대+",
};

const AGE_GROUP_OPTIONS = [
  AgeGroup.Teens,
  AgeGroup.Twenties,
  AgeGroup.Thirties,
  AgeGroup.Forties,
  AgeGroup.FiftiesPlus,
] as const;

interface AgeSegmentedControlProps {
  value: AgeGroup | undefined;
  onChange: (value: AgeGroup) => void;
  error?: string;
}

export function AgeSegmentedControl({ value, onChange, error }: AgeSegmentedControlProps) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-ink">연령대</span>
      <div
        className="flex h-[42px] rounded-lg bg-surface-2 p-0.5"
        role="radiogroup"
        aria-label="연령대"
      >
        {AGE_GROUP_OPTIONS.map((option) => {
          const selected = option === value;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(option)}
              className={[
                "flex-1 rounded-[7px] text-xs",
                selected
                  ? "border border-blue-point bg-blue-tint font-bold text-blue-point"
                  : "border border-transparent font-normal text-ink-soft",
              ].join(" ")}
            >
              {AGE_GROUP_LABEL[option]}
            </button>
          );
        })}
      </div>
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </div>
  );
}
