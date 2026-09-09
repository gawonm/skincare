"""서비스 사용자 계정(User).

이메일 하나로 로그인한다. 소셜 로그인·이메일 인증은 이번 범위에 없으므로 별도 상태
컬럼을 두지 않고, 계정 비활성화만 `is_active`로 표현한다.

비밀번호 원문은 저장하지 않는다. `hashed_password`에는 argon2id 해시 문자열만 들어간다.
해시 계산·검증은 `backend/services/security.py`가 담당하고, 이 모델은 값만 보관한다.
"""

from sqlalchemy import Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


class User(EntityBase):
    """이메일/비밀번호로 로그인하는 서비스 사용자."""

    # 테이블명은 `app_user`. `user`는 PostgreSQL 예약어라 원시 SQL에서 매번 따옴표가 필요하다.
    __tablename__ = "app_user"
    __table_args__ = (
        # 이메일을 로그인 식별자로 쓰므로 중복을 DB 레벨에서 막는다.
        UniqueConstraint("email", name="uq_app_user_email"),
        table_options(comment="이메일/비밀번호 로그인 사용자 계정"),
    )

    email: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="로그인 식별자. 대소문자를 구분하지 않도록 저장 전에 소문자로 정규화한다",
    )
    hashed_password: Mapped[str] = mapped_column(
        Text, nullable=False, comment="argon2id 해시 문자열. 원문 비밀번호는 저장하지 않는다"
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, comment="사용자 표시 이름")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="비활성 계정은 로그인과 세션 검증을 모두 거부한다",
    )
