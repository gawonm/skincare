"""`/auth` 엔드포인트.

함수는 얇게 유지한다. 요청을 받아 `AuthService`에 넘기고, 서비스가 던진 도메인 예외를
HTTP 상태 코드로 바꾸고, 세션 토큰을 쿠키에 싣는 일까지만 한다.

세션 토큰은 항상 `HttpOnly` 쿠키로만 내보낸다. 응답 본문에 넣지 않으므로 JS가 읽을 수
없고, XSS가 나도 토큰이 그대로 유출되지 않는다.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status

from backend.api.dependencies import AuthServiceDep, CurrentUserDep
from backend.schemas.auth import LoginRequest, SignupRequest, UserResponse
from backend.services.auth import (
    EmailAlreadyRegistered,
    EmailNotRegistered,
    InactiveAccount,
    InvalidPassword,
)
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


def _clear_session_cookie(response: Response) -> None:
    """쿠키를 지운다. 브라우저가 같은 쿠키로 인식하도록 domain/path를 설정 때와 맞춘다."""
    auth = settings.auth
    response.delete_cookie(
        key=auth.cookie_name,
        path="/",
        domain=auth.cookie_domain,
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


@router.post(
    "/login",
    response_model=UserResponse,
    summary="로그인",
)
async def login(
    payload: LoginRequest,
    response: Response,
    auth_service: AuthServiceDep,
) -> User:
    try:
        user, token = await auth_service.login(payload)
    except EmailNotRegistered as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="가입되지 않은 이메일입니다.",
        ) from e
    except InvalidPassword as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 올바르지 않습니다.",
        ) from e
    except InactiveAccount as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다. 관리자에게 문의해 주세요.",
        ) from e
    _set_session_cookie(response, token)
    return user


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="로그아웃",
)
async def logout(request: Request, auth_service: AuthServiceDep) -> Response:
    # 로그인 여부와 무관하게 호출할 수 있게 둔다. 쿠키가 있으면 서버 세션도 함께 지운다.
    token = request.cookies.get(settings.auth.cookie_name)
    if token is not None:
        await auth_service.logout(token)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response)
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    summary="현재 로그인한 사용자 정보",
)
async def me(current_user: CurrentUserDep) -> User:
    return current_user
