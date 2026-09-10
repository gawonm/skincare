"""FastAPI 진입점.

`uv run uvicorn backend.main:app` 또는 `just server` 로 실행한다.

host/port 같은 실행 옵션은 여기서 읽지 않는다. `justfile` 의 `server` 레시피가
uvicorn CLI 인자로 넘긴다. 설정이 config.yaml 과 CLI 두 군데로 갈라지면 어느 쪽이
적용됐는지 알기 어려워지기 때문이다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from core.config import settings
from core.database import Database
from core.redis import RedisClient

# 빌드된 프론트가 놓이는 자리. Dockerfile 이 1단계 산출물을 이 경로로 복사한다.
# 저장소 루트 기준이므로 backend/ 의 두 단계 위를 잡는다.
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_INDEX_FILENAME = "index.html"


class SpaStaticFiles(StaticFiles):
    """빌드된 SPA 를 서빙한다.

    react-router 가 만드는 `/login` 같은 주소는 서버에 실제 파일이 없다. 그대로 404 를
    내면 새로고침이나 주소창 직접 입력에서 화면이 깨지므로, 없는 경로는 index.html 로
    돌려주고 라우팅은 브라우저가 하게 둔다.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            # 404 만 index.html 로 대체한다. 권한 오류 등을 함께 삼키면 원인을 못 찾는다.
            if e.status_code != HTTPStatus.NOT_FOUND:
                raise
            return await super().get_response(FRONTEND_INDEX_FILENAME, scope)


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
        self._mount_frontend()

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
        # 라우터 모듈은 여기서만 import 한다. import 시점에 settings 를 읽으므로
        # 앱을 만들 때 한 번만 로드되게 한다.
        from backend.api.auth import router as auth_router

        self._app.include_router(auth_router)

    def _mount_frontend(self) -> None:
        """빌드된 프론트를 루트에 붙인다.

        라우터를 등록한 뒤에 마운트해야 `/auth` 같은 API 경로를 정적 파일이 가리지 않는다.
        dist 가 없으면(빌드 전 로컬 개발) 마운트하지 않는다. 개발에서는 Vite 개발 서버가
        프론트를 띄우고 이 앱은 API 만 담당하기 때문이다.
        """
        if not (FRONTEND_DIST_DIR / FRONTEND_INDEX_FILENAME).is_file():
            return

        self._app.mount(
            "/",
            SpaStaticFiles(directory=FRONTEND_DIST_DIR, html=True),
            name="frontend",
        )

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
