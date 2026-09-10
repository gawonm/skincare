/**
 * 폼 제출 버튼.
 *
 * 요청 진행중(`pending`)이면 비활성화하고 라벨을 바꿔, 같은 요청이 두 번 나가는 것을 막는다.
 */

interface SubmitButtonProps {
  pending: boolean;
  /** 평상시 라벨. */
  children: string;
  /** 진행중일 때 보여줄 라벨. */
  pendingLabel: string;
}

export function SubmitButton({ pending, children, pendingLabel }: SubmitButtonProps) {
  return (
    <button
      type="submit"
      disabled={pending}
      className={[
        "mt-2 rounded-md px-4 py-2 text-sm font-semibold text-white transition",
        pending ? "cursor-not-allowed bg-slate-400" : "bg-slate-900 hover:bg-slate-700",
      ].join(" ")}
    >
      {pending ? pendingLabel : children}
    </button>
  );
}
