"""회원가입·로그인·로그아웃·세션 검증의 업무 로직.

트랜잭션 경계(commit)는 여기서 정한다. FastAPI를 import하지 않는다. 실패는 이 모듈이
정의한 예외로 알리고, HTTP 상태 코드로의 변환은 `api/` 계층이 한다.

사용자 열거 방지보다 명확한 안내를 우선한다는 결정에 따라, "가입되지 않은 이메일"과
"비밀번호 불일치"를 서로 다른 예외로 구분한다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.session import SessionRepository
from backend.repositories.user import UserRepository
from backend.schemas.auth import LoginRequest, SignupRequest
from backend.services.security import PasswordHasher
from models import User


class AuthError(Exception):
    """인증 흐름에서 발생하는 실패의 공통 상위 타입."""


class EmailAlreadyRegistered(AuthError):
    """가입하려는 이메일이 이미 존재한다."""


class EmailNotRegistered(AuthError):
    """로그인하려는 이메일로 가입된 계정이 없다."""


class InvalidPassword(AuthError):
    """이메일은 존재하지만 비밀번호가 일치하지 않는다."""


class InactiveAccount(AuthError):
    """계정이 비활성 상태라 로그인을 거부한다."""


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

    async def login(self, payload: LoginRequest) -> tuple[User, str]:
        """이메일/비밀번호를 확인하고 세션을 발급한다. (User, 세션 토큰)."""
        user = await self._users.get_by_email(payload.email)
        if user is None:
            raise EmailNotRegistered(payload.email)
        if not self._hasher.verify(user.hashed_password, payload.password):
            raise InvalidPassword(payload.email)
        if not user.is_active:
            raise InactiveAccount(payload.email)

        # argon2 파라미터가 올라갔다면 지금 평문을 알고 있는 이 시점에 해시를 새로 만든다.
        if self._hasher.needs_rehash(user.hashed_password):
            await self._users.set_hashed_password(user, self._hasher.hash(payload.password))
            await self._session.commit()

        token = await self._sessions.create(user.id)
        return user, token

    async def logout(self, token: str) -> None:
        """세션을 무효화한다. DB 변경이 없으므로 커밋도 없다."""
        await self._sessions.delete(token)

    async def get_current_user(self, token: str) -> User | None:
        """세션 토큰으로 현재 로그인한 사용자를 찾는다.

        세션이 없거나 계정이 사라졌거나 비활성이면 None. 예외를 던지지 않는 이유는
        호출부(의존성)가 401 응답 처리를 맡기 때문이다.
        """
        record = await self._sessions.get(token)
        if record is None:
            return None
        user = await self._users.get_by_id(record.user_id)
        if user is None or not user.is_active:
            return None
        return user
