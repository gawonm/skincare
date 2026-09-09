"""회원가입·로그인·로그아웃·세션 검증의 업무 로직.

트랜잭션 경계(commit)는 여기서 정한다. FastAPI를 import하지 않는다. 실패는 이 모듈이
정의한 예외로 알리고, HTTP 상태 코드로의 변환은 `api/` 계층이 한다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.session import SessionRepository
from backend.repositories.user import UserRepository
from backend.schemas.auth import SignupRequest
from backend.services.security import PasswordHasher
from models import User


class AuthError(Exception):
    """인증 흐름에서 발생하는 실패의 공통 상위 타입."""


class EmailAlreadyRegistered(AuthError):
    """가입하려는 이메일이 이미 존재한다."""


class AuthService:
    """인증 유스케이스. 세션과 리포지토리, 해셔를 주입받아 조합한다.

    `session`은 두 리포지토리가 공유하는 바로 그 SQLAlchemy 세션이다. 커밋을 이 클래스가
    직접 호출해 트랜잭션 경계를 한 곳에 둔다.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        password_hasher: PasswordHasher,
    ) -> None:
        self._session = session
        self._users = user_repository
        self._sessions = session_repository
        self._hasher = password_hasher

    async def signup(self, payload: SignupRequest) -> tuple[User, str]:
        """계정을 만들고 곧바로 로그인 세션까지 발급한다. (생성된 User, 세션 토큰)."""
        if await self._users.exists_by_email(payload.email):
            raise EmailAlreadyRegistered(payload.email)

        hashed = self._hasher.hash(payload.password)
        user = await self._users.create(
            email=payload.email,
            hashed_password=hashed,
            name=payload.name,
        )
        # 계정 INSERT를 먼저 확정한 뒤 세션을 만든다. 반대 순서면 커밋이 실패했을 때
        # Redis에 주인 없는 세션이 남는다.
        await self._session.commit()
        token = await self._sessions.create(user.id)
        return user, token
