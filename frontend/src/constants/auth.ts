/**
 * `/auth` 화면이 공유하는 상수.
 *
 * 규칙 9(매직 넘버·문자열 금지)에 따라 엔드포인트 경로, 입력 길이 제한, 상태코드별
 * 사용자 문구를 한곳에 모은다. 백엔드(`backend/schemas/auth.py`, `backend/api/auth.py`)의
 * 값과 어긋나면 검증이 서로 다르게 동작하므로 항상 같이 확인한다.
 */

/** 백엔드 `/auth` 라우터의 경로. `vite.config.ts` 의 프록시 prefix(`/auth`)와 맞물린다. */
export enum AuthEndpoint {
  Signup = "/auth/signup",
  Login = "/auth/login",
}

// `docs/contracts/front-to-backend.md` "회원가입 확장" 절(확정됨)에 맞춘 값. `models/user.py`
// 의 `Gender`/`AgeGroup` 과 문자열 값이 같아야 한다 — 어긋나면 백엔드가 422 로 거부한다.
export enum Gender {
  Female = "female",
  Male = "male",
  Unspecified = "unspecified",
}

export enum AgeGroup {
  Teens = "10s",
  Twenties = "20s",
  Thirties = "30s",
  Forties = "40s",
  FiftiesPlus = "50s_plus",
}

// 비밀번호: 백엔드 `PasswordStr`(min 8 / max 1024)와 동일하게 맞춘다.
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 1024;

// 이름: 백엔드 `NameStr`(strip 후 1~100)과 동일.
export const NAME_MIN_LENGTH = 1;
export const NAME_MAX_LENGTH = 100;

/** HTTP 상태코드. 백엔드가 도메인 예외를 이 코드로 변환해 내려준다. */
export enum AuthHttpStatus {
  Unauthorized = 401,
  Forbidden = 403,
  Conflict = 409,
  UnprocessableEntity = 422,
}

/**
 * 상태코드 → 사용자에게 보여줄 한국어 문구(폴백).
 *
 * 백엔드가 `detail` 을 함께 내려주면 그쪽을 우선 쓰고(`resolveAuthErrorMessage`),
 * 네트워크 오류처럼 본문이 없을 때만 이 표를 쓴다.
 */
export const AUTH_ERROR_MESSAGE: Record<number, string> = {
  [AuthHttpStatus.Unauthorized]: "이메일 또는 비밀번호가 올바르지 않습니다.",
  [AuthHttpStatus.Forbidden]: "비활성화된 계정입니다. 관리자에게 문의해 주세요.",
  [AuthHttpStatus.Conflict]: "이미 사용 중인 이메일입니다.",
  [AuthHttpStatus.UnprocessableEntity]: "입력 값을 다시 확인해 주세요.",
};

/** 상태코드가 표에 없을 때(5xx, 프록시 502 등) 쓰는 문구. */
export const AUTH_ERROR_FALLBACK_MESSAGE =
  "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";

/** 서버에 닿지도 못했을 때(백엔드 미기동 등) 쓰는 문구. */
export const NETWORK_ERROR_MESSAGE =
  "서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인해 주세요.";
