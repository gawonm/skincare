/**
 * 홈 화면 샘플.
 *
 * 로그인 성공 후 이동이 실제로 일어나는지 확인하기 위한 최소 화면이다. 아직 보호
 * 라우트가 아니고(세션 없이 URL 을 직접 쳐도 열린다), 사용자 정보를 불러오지도 않는다.
 * "로그아웃" 버튼도 서버 세션은 건드리지 않고 로그인 화면으로 되돌리기만 한다.
 * 실제 인증 연동(GET /auth/me, POST /auth/logout)은 다음 작업으로 남겨 둔다.
 */

import { useNavigate } from "react-router-dom";

export function HomePage() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-bold text-slate-900">홈</h1>
        <p className="mt-1 text-sm text-slate-500">로그인되었습니다.</p>

        <button
          type="button"
          // 세션 정리 없이 화면 전환만 한다. 되돌아왔을 때 뒤로가기로 홈에 다시
          // 오지 않도록 replace 로 히스토리를 덮는다.
          onClick={() => navigate("/login", { replace: true })}
          className="mt-5 w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
        >
          로그아웃
        </button>
      </div>
    </div>
  );
}
