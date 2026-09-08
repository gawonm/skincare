"""enable pg_search and vector extensions

Revision ID: 0001_extensions
Revises:
Create Date: 2026-09-08

확장은 테이블보다 먼저 있어야 한다. 벡터 컬럼이나 BM25 인덱스를 만드는 리비전이
이 리비전 뒤에 오도록 체인의 맨 앞에 둔다.

`CREATE EXTENSION` 은 superuser 권한이 필요하다. 컴포즈의 `POSTGRES_USER` 는
superuser 지만, 관리형 PostgreSQL 이라면 확장이 허용 목록에 있는지 먼저 확인한다.
"""

from collections.abc import Sequence
from enum import StrEnum

from alembic import op

# Alembic 이 사용하는 리비전 식별자.
revision: str = "0001_extensions"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class Extension(StrEnum):
    """이 프로젝트가 요구하는 PostgreSQL 확장."""

    # BM25 전문 검색 인덱스(`USING bm25`).
    PG_SEARCH = "pg_search"
    # 벡터 타입과 ANN 인덱스(hnsw, ivfflat). 확장 이름은 `pgvector` 가 아니라 `vector`.
    VECTOR = "vector"


def upgrade() -> None:
    for extension in Extension:
        # 이미 만들어져 있어도 실패하지 않게 IF NOT EXISTS 를 붙인다. 확장을 미리
        # 깔아 둔 운영 DB 에도 같은 리비전을 그대로 올릴 수 있다.
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension.value}")


def downgrade() -> None:
    # 확장은 지우지 않는다. `DROP EXTENSION` 은 그 타입을 쓰는 컬럼과 인덱스를 함께
    # 지우기 때문에, 같은 DB 를 쓰는 다른 스키마의 데이터까지 날아갈 수 있다.
    # 정말 제거해야 하면 아래를 직접 실행한다.
    #   DROP EXTENSION IF EXISTS vector;
    #   DROP EXTENSION IF EXISTS pg_search;
    pass
