"""데이터베이스 설정과 SQLAlchemy declarative base.

단일 데이터베이스를 전제로 한다. 테이블이 이 프로젝트의 마이그레이션 소유인지 여부만
모델이 `table_options`로 선언하고, `migrations/env.py`가 그 값을 읽어 autogenerate
범위를 정한다.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlalchemy import DateTime, Table, Uuid, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class DatabaseConfig(PydanticBaseModel):
    """`config.yaml`의 `database` 블록.

    `model_modules`는 Alembic autogenerate 전에 import 할 모델 모듈이다. 런타임
    애플리케이션은 이 값을 쓰지 않는다.
    """

    model_config = ConfigDict(frozen=True)

    url: Annotated[str, Field(min_length=1)]
    model_modules: tuple[str, ...] = ()


def _connect_args_for(config: DatabaseConfig) -> dict[str, dict[str, str]]:
    return {"server_settings": {"timezone": "UTC"}}


def table_options(*, comment: str, managed: bool = True) -> dict[str, object]:
    """`__table_args__`의 마지막 요소로 쓰는 dict를 만든다.

    스키마는 지정하지 않는다. 연결의 `search_path`(PostgreSQL 기본 `public`)를 따른다.

    `managed=False`는 이 프로젝트가 스키마를 소유하지 않는 테이블이다. ORM 매핑은
    유지해서 읽고 쓸 수 있지만 autogenerate에 나오지 않는다. Django의
    `Meta.managed = False`와 같은 뜻이며, 런타임 쓰기 금지와는 관계가 없다.
    """
    return {
        "comment": comment,
        "info": {"managed": managed},
    }


def table_managed(table: Table) -> bool:
    """이 프로젝트의 마이그레이션이 스키마를 소유하는 테이블인지. 선언이 없으면 소유한다."""
    managed = table.info.get("managed", True)
    if not isinstance(managed, bool):
        raise TypeError(f"Table {table.fullname!r} declared a non-boolean managed flag")
    return managed


class Base(DeclarativeBase):
    """ORM 모델의 공용 declarative base."""


class EntityBase(Base):
    """모든 애플리케이션 테이블이 공유하는 식별자와 UTC 시각.

    공통 컬럼 주석을 여기서 한 번만 정의한다. 이 규칙이 필요 없으면 `Base`를 직접 상속한다.
    """

    __abstract__ = True

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        comment="레코드 고유 식별자",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="레코드 생성 시각(UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="레코드 최종 수정 시각(UTC)",
    )


class Database:
    """런타임에서 쓰는 engine과 session factory."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._engine = create_async_engine(
            config.url,
            pool_pre_ping=True,
            connect_args=_connect_args_for(config),
        )
        self._session_factory = async_sessionmaker(bind=self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def dispose(self) -> None:
        await self._engine.dispose()
