"""`config.yaml` 하나만 설정 소스로 쓰는 Pydantic 설정.

환경 변수와 `.env`는 읽지 않는다. 프로젝트에 다른 설정 항목이 있으면 `Settings`에 필드를
추가하면 된다. `migrations/`가 요구하는 것은 `database` 하나뿐이다.

`.env.example`은 Docker Compose 전용이라 이 파일과 무관하다. 컴포즈에서 포트나 계정을
바꿨다면 `config.yaml`의 URL도 같이 고쳐야 한다.
"""

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
