"""FastAPI 진입점.

`uv run uvicorn backend.main:app` 또는 `just server` 로 실행한다.

host/port 같은 실행 옵션은 여기서 읽지 않는다. `justfile` 의 `server` 레시피가
uvicorn CLI 인자로 넘긴다. 설정이 config.yaml 과 CLI 두 군데로 갈라지면 어느 쪽이
적용됐는지 알기 어려워지기 때문이다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import settings
from core.database import Database
from core.redis import RedisClient


class Application:
    """FastAPI 앱 생성과 프로세스 수명 동안의 자원 관리를 한 곳에 묶는다.

    Database 와 RedisClient 는 연결 풀을 들고 있어서 요청마다 만들면 안 된다.
    시작할 때 하나씩 만들어 `app.state` 에 두고, 종료할 때 반드시 정리한다.
    """

    def __init__(self) -> None:
        self._database: Database | None = None
        self._redis: RedisClient | None = None
        self._app = FastAPI(
            title=settings.app.title,
            lifespan=self._lifespan,
        )
        self._register_routers()

    @property
    def app(self) -> FastAPI:
        return self._app

    @property
    def database(self) -> Database:
        # lifespan 밖에서 접근하면(예: import 시점) None 이라 여기서 걸러 준다.
        if self._database is None:
            raise RuntimeError("Database is not initialized: application lifespan has not started")
        return self._database

    @property
    def redis(self) -> RedisClient:
        if self._redis is None:
            raise RuntimeError("Redis is not initialized: application lifespan has not started")
        return self._redis

    def _register_routers(self) -> None:
        # 라우터가 생기면 여기서 include_router 한다. 아직 엔드포인트가 없다.
        return

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database)
        redis = RedisClient(settings.redis)

        # Redis 는 명령을 보낼 때까지 연결을 열지 않는다. 기동 시 한 번 ping 해서
        # 설정이 틀렸으면 첫 요청이 아니라 지금 실패하게 만든다.
        try:
            await redis.ping()
        except OSError as e:
            await redis.close()
            await database.dispose()
            raise RuntimeError(f"Redis 연결 실패({settings.redis.url}): {e}") from e

        self._database = database
        self._redis = redis
        app.state.database = database
        app.state.redis = redis

        try:
            yield
        finally:
            # 시작 중 예외가 나도 연결 풀이 남지 않도록 finally 에서 정리한다.
            self._database = None
            self._redis = None
            await redis.close()
            await database.dispose()


application = Application()
app = application.app
