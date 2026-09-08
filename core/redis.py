"""Redis 설정과 런타임 클라이언트.

`core/database.py` 와 같은 모양이다. `config.yaml` 의 `redis` 블록을 `RedisConfig` 가
검증하고, `RedisClient` 가 연결 풀을 하나 만들어 애플리케이션 수명 동안 재사용한다.
마이그레이션은 Redis 를 쓰지 않는다.
"""

from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisConfig(PydanticBaseModel):
    """`config.yaml` 의 `redis` 블록."""

    model_config = ConfigDict(frozen=True)

    # `redis://호스트:포트/DB번호`. DB 번호는 0~15 의 논리 분리 공간이다.
    url: Annotated[str, Field(min_length=1)] = "redis://localhost:6379/0"
    # 풀이 동시에 여는 최대 연결 수.
    max_connections: Annotated[int, Field(gt=0)] = 20
    # True 면 응답이 str, False 면 bytes 로 온다. 직렬화한 값을 그대로 넣고 뺄
    # 생각이면 False 로 둔다.
    decode_responses: bool = True


class RedisClient:
    """런타임에서 쓰는 Redis 연결 풀.

    요청마다 만들지 않는다. 애플리케이션 시작 시 하나 만들고 종료 시 `close()` 한다.
    """

    def __init__(self, config: RedisConfig) -> None:
        # 여기서 import 한다. 그래야 Redis 를 쓰지 않는 Alembic 실행에
        # `redis` 패키지가 필요 없다.
        from redis.asyncio import ConnectionPool, Redis

        self._pool: ConnectionPool = ConnectionPool.from_url(
            config.url,
            max_connections=config.max_connections,
            decode_responses=config.decode_responses,
            # 유휴 연결이 죽었는지 주기적으로 확인한다. 없으면 서버 재시작 직후
            # 첫 명령이 ConnectionError 로 실패할 수 있다.
            health_check_interval=30,
        )
        self._client: Redis = Redis(connection_pool=self._pool)

    @property
    def client(self) -> "Redis":
        """명령을 실행할 클라이언트. `await redis.client.get("key")` 처럼 쓴다."""
        return self._client

    async def ping(self) -> bool:
        """연결 확인용. 기동 시 헬스 체크에 쓴다."""
        return bool(await self._client.ping())

    async def close(self) -> None:
        await self._client.aclose()
        await self._pool.disconnect()
