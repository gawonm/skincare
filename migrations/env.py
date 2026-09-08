"""단일 데이터베이스용 Alembic 환경.

연결 URL 과 모델 모듈을 `alembic.ini` 가 아니라 `config.yaml` 에서 읽는다. 그래서
`alembic` CLI 를 그대로 쓸 수 있다. 훅 두 개가 남의 테이블을 건드리지 않게 막는다.
"""

import asyncio
import importlib
import logging
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings
from core.database import Base
from migrations.routing import excluded_tables, include_table, mapped_tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

database = settings.database

# import 하지 않은 모델은 `Base.metadata` 에 없다. autogenerate 는 그 테이블을
# "사라진 테이블"로 보고 DROP 을 만든다.
for module_name in sorted(set(database.model_modules)):
    importlib.import_module(module_name)

target_metadata = Base.metadata if database.model_modules else None

PARTITION_QUERY = """
SELECT n.nspname, c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relispartition
"""


def _filters(partitions: frozenset[tuple[str, str]]):
    """이번 실행에 쓸 `include_name`, `include_object` 훅.

    `include_name` 은 DB 에서 읽어온 이름만 본다(불필요한 DROP 차단).
    `include_object` 는 모델 metadata 까지 본다(`managed=False` 테이블 CREATE 차단).
    둘 다 필요하다.
    """
    tables = Base.metadata.tables.values()
    excluded = excluded_tables(tables)
    mapped = mapped_tables(tables)

    def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
        if type_ == "table":
            return include_table(
                name,
                parent_names.get("schema_name"),
                reflected=True,
                partitions=partitions,
                excluded=excluded,
                mapped=mapped,
            )
        return True

    def include_object(
        object_: sa.schema.SchemaItem,
        name: str | None,
        type_: str,
        reflected: bool,
        compare_to: object,
    ) -> bool:
        if type_ == "table":
            return include_table(
                name,
                object_.schema,
                reflected=reflected,
                partitions=partitions,
                excluded=excluded,
                mapped=mapped,
            )
        return True

    return include_name, include_object


def _configure(partitions: frozenset[tuple[str, str]], **kwargs: object) -> None:
    include_name, include_object = _filters(partitions)
    context.configure(
        target_metadata=target_metadata,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """오프라인 모드. DB 에 붙지 않고 SQL 만 출력한다."""
    _configure(
        frozenset(),
        url=database.url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    partitions = frozenset((schema, name) for schema, name in connection.execute(sa.text(PARTITION_QUERY)).all())
    # 위 조회가 트랜잭션을 열었다. `context.begin_transaction()` 은 연결에 트랜잭션이
    # 없을 때만 주도권을 잡고 커밋한다. 여기서 닫지 않으면 마이그레이션 전체가 연결을
    # 닫을 때 조용히 롤백된다.
    connection.rollback()

    _configure(partitions, connection=connection)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(database.url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """온라인 모드. 실제 DB 에 접속해 실행한다."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
