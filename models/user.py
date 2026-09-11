"""서비스 사용자 계정(User).

이메일 하나로 로그인한다. 소셜 로그인·이메일 인증은 이번 범위에 없으므로 별도 상태
컬럼을 두지 않고, 계정 비활성화만 `is_active`로 표현한다.

비밀번호 원문은 저장하지 않는다. `hashed_password`에는 argon2id 해시 문자열만 들어간다.
해시 계산·검증은 `backend/services/security.py`가 담당하고, 이 모델은 값만 보관한다.

`gender`/`age_group`/`terms_agreed*`는 피그마 회원가입 시안에 맞춰 추가됐다
(`docs/contracts/front-to-backend.md` "회원가입 확장" 절, `docs/erd/app.md` 승인 완료).
별도 프로필 테이블로 분리하지 않은 이유는 ERD 문서에 적었다 — 지금은 계정과 1:1이고
다른 테이블이 참조하지도 않아서, 분리가 조인만 늘릴 뿐 얻는 게 없다.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


def _sql_enum(enum_cls: type[StrEnum], *, length: int) -> SqlEnum:
    # native_enum=False: PostgreSQL ENUM 타입 대신 VARCHAR+CHECK로 저장한다. 값 추가/삭제가
    # 마이그레이션 없이(모델 변경만으로) 되지는 않지만, 기존 성분 테이블들과 일관된 방식이다.
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class Gender(StrEnum):
    """가입 시 선택하는 성별. 프론트 계약(`docs/contracts/front-to-backend.md`)과 값을 맞춘다."""

    FEMALE = "female"
    MALE = "male"
    UNSPECIFIED = "unspecified"


class AgeGroup(StrEnum):
    """가입 시 선택하는 연령대."""

    TEENS = "10s"
    TWENTIES = "20s"
    THIRTIES = "30s"
    FORTIES = "40s"
    FIFTIES_PLUS = "50s_plus"


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
    gender: Mapped[Gender] = mapped_column(
        _sql_enum(Gender, length=20), nullable=False, comment="가입 시 선택한 성별"
    )
    age_group: Mapped[AgeGroup] = mapped_column(
        _sql_enum(AgeGroup, length=20), nullable=False, comment="가입 시 선택한 연령대"
    )
    terms_agreed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="이용약관·개인정보 처리방침 동의 여부. 가입 게이트라 사실상 항상 true만 저장된다",
    )
    terms_agreed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="약관 동의 시각(감사용). terms_agreed=false일 때는 NULL",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="비활성 계정은 로그인과 세션 검증을 모두 거부한다",
    )
