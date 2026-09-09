"""`/auth` 엔드포인트.

함수는 얇게 유지한다. 요청을 받아 `AuthService`에 넘기고, 서비스가 던진 도메인 예외를
HTTP 상태 코드로 바꾸고, 세션 토큰을 쿠키에 싣는 일까지만 한다.

세션 토큰은 항상 `HttpOnly` 쿠키로만 내보낸다. 응답 본문에 넣지 않으므로 JS가 읽을 수
없고, XSS가 나도 토큰이 그대로 유출되지 않는다.
"""

from fastapi import APIRouter, HTTPException, Response, status

from backend.api.dependencies import AuthServiceDep
from backend.schemas.auth import SignupRequest, UserResponse
from backend.services.auth import EmailAlreadyRegistered
from core.config import settings
from models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    """세션 토큰을 쿠키에 싣는다. 속성은 전부 `config.yaml`의 `auth` 블록에서 온다."""
    auth = settings.auth
    response.set_cookie(
        key=auth.cookie_name,
        value=token,
        max_age=auth.session_ttl_seconds,
        path="/",
        domain=auth.cookie_domain,
        secure=auth.cookie_secure,
        httponly=True,
        samesite=auth.cookie_samesite.value,
    )


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입(성공 시 자동 로그인)",
)
async def signup(
    payload: SignupRequest,
    response: Response,
    auth_service: AuthServiceDep,
) -> User:
    try:
        user, token = await auth_service.signup(payload)
    except EmailAlreadyRegistered as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다.",
        ) from e
    _set_session_cookie(response, token)
    return user
