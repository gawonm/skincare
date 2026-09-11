"""`user_account` 테이블 조회/저장. SQLAlchemy 쿼리는 이 계층에만 둔다.

세션은 생성자에서 주입받는다. `commit`은 하지 않는다. 트랜잭션 경계는 서비스가 정한다.
`flush`는 INSERT를 DB로 내보내 서버 기본값(id, created_at)을 채우기 위한 것이며 커밋이
아니므로 여기서 호출한다.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AgeGroup, Gender, User


class UserRepository:
    """`user_account` 한 테이블에 대한 조회/저장."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        """로그인 식별자로 계정을 찾는다. 이메일은 호출 전에 소문자로 정규화돼 있어야 한다."""
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        """세션에 저장된 user_id로 계정을 다시 읽는다. 세션 검증 시마다 최신 is_active를 확인하기 위함."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def exists_by_email(self, email: str) -> bool:
        """가입 시 이메일 중복 확인용. 행 전체를 읽지 않고 존재 여부만 본다."""
        result = await self._session.execute(select(User.id).where(User.email == email).limit(1))
        return result.first() is not None

    async def create(
        self,
        *,
        email: str,
        hashed_password: str,
        name: str,
        gender: Gender,
        age_group: AgeGroup,
        terms_agreed_at: datetime,
    ) -> User:
        """새 계정을 INSERT하고 서버 기본값이 채워진 인스턴스를 돌려준다.

        `terms_agreed`는 여기서 항상 True다 — 서비스가 `SignupRequest.terms_agreed`를
        `Literal[True]`로 검증한 뒤에만 이 메서드를 호출하기 때문이다.
        """
        user = User(
            email=email,
            hashed_password=hashed_password,
            name=name,
            gender=gender,
            age_group=age_group,
            terms_agreed=True,
            terms_agreed_at=terms_agreed_at,
        )
        self._session.add(user)
        # id·created_at 같은 서버 기본값을 이 자리에서 채워 호출자가 바로 응답에 쓸 수 있게 한다.
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def set_hashed_password(self, user: User, hashed_password: str) -> None:
        """argon2 파라미터가 올라갔을 때 로그인 성공 시점에 해시를 새 값으로 교체한다."""
        user.hashed_password = hashed_password
        self._session.add(user)
        await self._session.flush()
