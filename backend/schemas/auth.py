"""`/auth` 엔드포인트의 요청/응답 모델.

`models.User`(SQLAlchemy 테이블)를 그대로 응답으로 내보내지 않는다. `hashed_password`
같은 내부 컬럼이 노출되고, 테이블을 바꾸면 API 계약이 함께 깨지기 때문이다.

이메일은 `pydantic.EmailStr`(내부적으로 `email-validator`)로 형식을 검증한다. 실제 도달
가능 여부(이메일 인증 메일 발송)는 이번 범위에 없다.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

# argon2id 는 bcrypt 와 달리 입력 길이 제한이 없지만, 과도하게 긴 입력으로 해시 계산을
# 유발하는 것을 막기 위해 상한을 둔다.
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_MAX_LENGTH = 1024

PasswordStr = Annotated[
    str,
    Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH),
]
NameStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class _EmailNormalizingModel(BaseModel):
    """이메일을 로그인 키로 쓰므로 대소문자 차이를 없애기 위해 저장·조회 전에 소문자로 맞춘다."""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def _lowercase_email(cls, value: str) -> str:
        return value.lower()


class SignupRequest(_EmailNormalizingModel):
    """회원가입 입력. 비밀번호 복잡도는 요구하지 않고 최소 길이만 본다."""

    password: PasswordStr
    name: NameStr


class LoginRequest(_EmailNormalizingModel):
    """로그인 입력."""

    password: PasswordStr


class UserResponse(BaseModel):
    """계정 정보 응답. 내부 컬럼(hashed_password 등)은 담지 않는다."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    is_active: bool
    created_at: datetime
