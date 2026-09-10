/**
 * 백엔드 호출 공통 래퍼.
 *
 * 규칙 7(에러를 숨기지 않는다): 비-2xx 응답과 네트워크 실패를 조용히 삼키지 않고
 * 원인이 드러나는 `ApiError` 로 바꿔 던진다. 호출부(훅·페이지)는 이 예외를
 * 상태코드/문구로 사용자에게 보여준다.
 */

import {
  AUTH_ERROR_FALLBACK_MESSAGE,
  AUTH_ERROR_MESSAGE,
  NETWORK_ERROR_MESSAGE,
} from "../constants/auth";

/** FastAPI 의 에러 응답 형태. `HTTPException(detail=...)` 이 이 모양으로 직렬화된다. */
interface FastApiErrorBody {
  detail?: unknown;
}

/**
 * 요청이 성공하지 못했음을 나타내는 예외.
 *
 * `status` 가 0 이면 서버에 닿지도 못한 것(네트워크/프록시 실패)이고,
 * 그 외에는 백엔드가 실제로 내려준 HTTP 상태코드다.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "ApiError";
    this.status = status;
  }

  /** 서버 응답조차 받지 못한 경우인지. (배너 문구를 다르게 주기 위함) */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

/** FastAPI `detail` 은 문자열일 수도, 검증 에러 배열일 수도 있어 문자열일 때만 취한다. */
function extractDetailMessage(body: FastApiErrorBody | null): string | null {
  if (body !== null && typeof body.detail === "string" && body.detail.length > 0) {
    return body.detail;
  }
  return null;
}

/** 상태코드에 대응하는 폴백 문구. 표에 없으면 공통 폴백. */
function fallbackMessageFor(status: number): string {
  return AUTH_ERROR_MESSAGE[status] ?? AUTH_ERROR_FALLBACK_MESSAGE;
}

/**
 * JSON 요청/응답 헬퍼.
 *
 * - 항상 쿠키를 주고받는다(`credentials: "include"`). 로그인 세션이 HttpOnly 쿠키라서
 *   이 옵션이 없으면 `Set-Cookie` 가 저장되지 않는다.
 * - 204(No Content)면 본문 파싱을 건너뛰고 `undefined` 를 돌려준다.
 */
export async function fetchJson<TResponse>(
  path: string,
  init: RequestInit = {},
): Promise<TResponse> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...init.headers,
      },
    });
  } catch (cause) {
    // fetch 자체가 거부됨: 백엔드 미기동, DNS, 프록시 연결 실패 등.
    throw new ApiError(0, NETWORK_ERROR_MESSAGE, { cause });
  }

  if (!response.ok) {
    // 에러 본문이 JSON 이 아닐 수도 있으므로(프록시 502 HTML 등) 파싱 실패를 흡수한다.
    let body: FastApiErrorBody | null = null;
    try {
      body = (await response.json()) as FastApiErrorBody;
    } catch {
      body = null;
    }
    const message = extractDetailMessage(body) ?? fallbackMessageFor(response.status);
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }
  return (await response.json()) as TResponse;
}
