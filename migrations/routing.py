"""autogenerate 가 손대도 되는 테이블인지 판정한다.

`env.py` 는 Alembic 실행 중에만 import 되므로 테스트가 안 된다. 그래서 판정 규칙만
여기로 뺐다.
"""

from collections.abc import Container, Iterable

from sqlalchemy import Table

from core.database import table_managed

TableKey = tuple[str | None, str | None]


def excluded_tables(tables: Iterable[Table]) -> frozenset[TableKey]:
    """autogenerate 가 건드리면 안 되는 테이블.

    `managed=False` 는 매핑만 하고 스키마는 남이 소유한 테이블이다.
    """
    return frozenset((table.schema, table.name) for table in tables if not table_managed(table))


def mapped_tables(tables: Iterable[Table]) -> frozenset[TableKey]:
    """이 프로젝트가 매핑한 모든 테이블."""
    return frozenset((table.schema, table.name) for table in tables)


def include_table(
    name: str | None,
    schema: str | None,
    *,
    reflected: bool,
    partitions: Container[TableKey],
    excluded: Container[TableKey],
    mapped: Container[TableKey],
) -> bool:
    """이 테이블을 autogenerate 대상으로 삼을지.

    Alembic 이 `include_name` 과 `include_object` 두 훅으로 따로 묻는다. 답이 갈리지
    않도록 둘 다 이 함수에 위임한다.
    """
    if (schema, name) in partitions:
        # 파티션 자식 테이블은 모델이 아니라 마이그레이션이나 운영 작업이 만든다.
        return False
    if (schema, name) in excluded:
        return False
    # DB 에는 있는데 매핑한 모델이 없으면 남의 테이블이다. DROP 을 내지 않는다.
    # 반대로 모델 쪽(reflected=False)은 아직 DB 에 없는 게 정상이라 통과시킨다.
    return not reflected or (schema, name) in mapped
