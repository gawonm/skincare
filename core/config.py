"""`config.yaml` 하나만 설정 소스로 쓰는 Pydantic 설정.

환경 변수와 `.env`는 읽지 않는다. 프로젝트에 다른 설정 항목이 있으면 `Settings`에 필드를
추가하면 된다. `migrations/`가 요구하는 것은 `database` 하나뿐이다.

`.env.example`은 Docker Compose 전용이라 이 파일과 무관하다. 컴포즈에서 포트나 계정을
바꿨다면 `config.yaml`의 URL도 같이 고쳐야 한다.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from core.database import DatabaseConfig
from core.redis import RedisConfig


class CookieSameSite(StrEnum):
    """세션 쿠키의 SameSite 정책. Starlette 응답 API가 받는 소문자 리터럴과 값을 맞춘다."""

    LAX = "lax"
    STRICT = "strict"
    NONE = "none"


class AuthConfig(PydanticBaseModel):
    """`config.yaml`의 `auth` 블록. 로그인 세션과 세션 쿠키 설정.

    세션 자체는 Redis에 저장하고 여기서는 만료 시간과 쿠키 속성만 다룬다. JWT를 쓰지
    않으므로 서명 비밀키가 필요 없다. 블록이 없으면 아래 기본값이 그대로 쓰인다.
    """

    model_config = ConfigDict(frozen=True)

    # 세션 만료 시간(초). 기본 14일.
    session_ttl_seconds: Annotated[int, Field(gt=0)] = 60 * 60 * 24 * 14
    # 세션 ID를 담는 쿠키 이름.
    cookie_name: Annotated[str, Field(min_length=1)] = "session_id"
    # HTTPS 연결에서만 쿠키를 전송할지. 로컬 http 개발은 False, 배포는 True.
    cookie_secure: bool = False
    # 크로스 사이트 요청에 쿠키를 붙일지. NONE은 브라우저가 cookie_secure=True를 요구한다.
    cookie_samesite: CookieSameSite = CookieSameSite.LAX
    # 쿠키를 공유할 도메인. None이면 요청 호스트에만 한정된다.
    cookie_domain: str | None = None


class MfdsConfig(PydanticBaseModel):
    """`config.yaml`의 `mfds` 블록. 공공데이터포털 식약처 OpenAPI 인증 정보.

    서비스키는 비밀값이라 `.env`가 아니라 여기(`config.yaml`, gitignore 대상)에 둔다.
    이 프로젝트의 설정 소스는 `config.yaml` 하나뿐이라는 원칙을 따른 것이다.
    """

    model_config = ConfigDict(frozen=True)

    service_key: Annotated[str, Field(min_length=1)]
    base_url: Annotated[str, Field(min_length=1)] = (
        "https://apis.data.go.kr/1471000/CsmtcsUseRstrcInfoService"
    )


class OpenAiConfig(PydanticBaseModel):
    """`config.yaml`의 `openai` 블록. RAG 임베딩·답변 생성에 쓰는 OpenAI 인증·모델 설정.

    API 키는 비밀값이라 `.env`가 아니라 여기(`config.yaml`, gitignore 대상)에 둔다.
    임베딩 모델을 바꾸면 기존 `rag_chunk.embedding` 벡터를 전부 다시 만들어야 하므로,
    모델명은 기본값을 두되 바꿀 때는 재임베딩이 필요하다는 걸 알고 바꿔야 한다.
    """

    model_config = ConfigDict(frozen=True)

    api_key: Annotated[str, Field(min_length=1)]
    embedding_model: Annotated[str, Field(min_length=1)] = "text-embedding-3-small"
    chat_model: Annotated[str, Field(min_length=1)] = "gpt-4.1-mini"


class AppConfig(PydanticBaseModel):
    """`config.yaml`의 `app` 블록.

    host/port는 여기에 두지 않는다. 그 값은 `justfile`이 uvicorn CLI 인자로 넘긴다.
    설정이 config.yaml과 CLI 두 군데로 갈라지면 어느 쪽이 적용됐는지 알기 어렵다.
    """

    model_config = ConfigDict(frozen=True)

    # OpenAPI 문서와 `/docs` 상단에 표시되는 이름.
    title: Annotated[str, Field(min_length=1)] = "alembic-singledb"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file="config.yaml",
        yaml_file_encoding="utf-8",
        extra="ignore",
    )

    database: DatabaseConfig
    # `redis` 블록이 없으면 기본값(redis://localhost:6379/0)을 쓴다.
    redis: RedisConfig = RedisConfig()
    # `app` 블록이 없으면 기본 제목을 쓴다.
    app: AppConfig = AppConfig()
    # `auth` 블록이 없으면 기본 세션/쿠키 설정을 쓴다.
    auth: AuthConfig = AuthConfig()
    # `mfds` 블록이 없으면 None. MFDS 연동 스크립트를 실행할 때만 필요하다.
    mfds: MfdsConfig | None = None
    # `openai` 블록이 없으면 None. RAG 임베딩·생성 파이프라인을 실행할 때만 필요하다.
    openai: OpenAiConfig | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (init_settings, YamlConfigSettingsSource(settings_cls))


settings = Settings()
