/**
 * 폼 상단에 뜨는 알림 배너.
 *
 * `tone` 에 따라 색만 바꾼다. 성공/실패 메시지를 같은 자리에서 보여줘 사용자가
 * 결과를 한곳에서 확인하게 한다.
 */

export type FormAlertTone = "error" | "success";

interface FormAlertProps {
  tone: FormAlertTone;
  message: string;
}

const TONE_CLASS: Record<FormAlertTone, string> = {
  error: "border-red-300 bg-red-50 text-red-700",
  success: "border-emerald-300 bg-emerald-50 text-emerald-700",
};

export function FormAlert({ tone, message }: FormAlertProps) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-md border px-3 py-2 text-sm ${TONE_CLASS[tone]}`}
    >
      {message}
    </div>
  );
}
