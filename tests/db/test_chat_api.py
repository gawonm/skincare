"""`POST /chat` 엔드포인트를 실제 DB 히스토리와 개발용 Agent로 검증한다.

앱 전체(lifespan, Redis)를 띄우지 않고 채팅 라우터만 붙인 작은 FastAPI 앱을 쓴다. 로그인은 의존성
교체로 대신하고, `session` 픽스처의 SAVEPOINT 위에서 돌아 로컬 DB에 데이터가 남지 않는다.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.schemas import ChatStatus
from backend.api.chat import router as chat_router
from backend.api.dependencies import (
    AGENT_CHAT_SERVICE_STATE_NAME,
    get_auth_service,
    get_current_user,
)
from backend.main import SpaStaticFiles
from backend.services.chat_history import SqlAlchemyChatHistoryRepository
from models.user import User
from tests.db.test_chat_history import ChatHistoryFixtures
from tests.db.test_chat_service_integration import SqlHistoryAgentFactory

CHAT_PATH = "/chat"
SPA_INDEX_MARKER = "<title>spa-index</title>"


class StubAuthService:
    """쿠키가 없거나 무효인 요청이 401이 되는지만 보려고 항상 "로그인 안 함"으로 답한다."""

    async def get_current_user(self, token: str) -> None:
        return None


class ChatApiAppFactory:
    """채팅 라우터만 붙인 테스트용 앱을 만든다."""

    def create(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        user: User | None,
        with_agent: bool = True,
    ) -> FastAPI:
        app = FastAPI()
        app.include_router(chat_router)
        app.state.database = SimpleNamespace(session_factory=session_factory)
        if with_agent:
            history = SqlAlchemyChatHistoryRepository(session_factory)
            setattr(
                app.state,
                AGENT_CHAT_SERVICE_STATE_NAME,
                SqlHistoryAgentFactory().create(history),
            )
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
        else:
            app.dependency_overrides[get_auth_service] = StubAuthService
        return app


@pytest.fixture
def session_factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest_asyncio.fixture
async def user(session: AsyncSession) -> User:
    return await ChatHistoryFixtures().create_user(session)


async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], user: User
) -> AsyncIterator[AsyncClient]:
    app = ChatApiAppFactory().create(session_factory, user=user)
    async for client in client_for(app):
        yield client


class TestPostChat:
    async def test_completed_turn_returns_json_with_server_side_room(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            CHAT_PATH, json={"request_id": "r1", "message": "가벼운 보습 크림 추천해줘"}
        )

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == ChatStatus.COMPLETED.value
        assert body["request_id"] == "r1"
        assert body["chat_room_id"]
        assert body["artifacts"]

    async def test_same_user_keeps_the_same_room_across_turns(self, client: AsyncClient) -> None:
        first = await client.post(CHAT_PATH, json={"request_id": "r1", "message": "안녕"})
        second = await client.post(CHAT_PATH, json={"request_id": "r2", "message": "안녕하세요"})

        assert first.json()["chat_room_id"] == second.json()["chat_room_id"]

    async def test_repeated_request_id_returns_the_stored_response(
        self, client: AsyncClient
    ) -> None:
        payload = {"request_id": "r1", "message": "가벼운 보습 크림 추천해줘"}
        first = await client.post(CHAT_PATH, json=payload)

        replay = await client.post(CHAT_PATH, json=payload)

        assert replay.status_code == 200
        assert replay.json() == first.json()

    async def test_agent_error_is_a_200_response_with_error_code(self, client: AsyncClient) -> None:
        await client.post(CHAT_PATH, json={"request_id": "r1", "message": "안녕"})

        conflict = await client.post(CHAT_PATH, json={"request_id": "r1", "message": "다른 내용"})

        body = conflict.json()
        assert conflict.status_code == 200
        assert body["status"] == ChatStatus.ERROR.value
        assert body["error_code"] == "request_conflict"

    @pytest.mark.parametrize(
        "payload",
        [
            {"request_id": "r1", "message": ""},
            {"request_id": "", "message": "안녕"},
            {"message": "안녕"},
        ],
    )
    async def test_invalid_body_is_422(self, client: AsyncClient, payload: dict[str, str]) -> None:
        response = await client.post(CHAT_PATH, json=payload)

        assert response.status_code == 422


class TestChatApiGuards:
    async def test_unauthenticated_request_is_401(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        app = ChatApiAppFactory().create(session_factory, user=None)
        async for client in client_for(app):
            response = await client.post(CHAT_PATH, json={"request_id": "r1", "message": "안녕"})

        assert response.status_code == 401

    async def test_missing_agent_is_503(
        self, session_factory: async_sessionmaker[AsyncSession], user: User
    ) -> None:
        app = ChatApiAppFactory().create(session_factory, user=user, with_agent=False)
        async for client in client_for(app):
            response = await client.post(CHAT_PATH, json={"request_id": "r1", "message": "안녕"})

        assert response.status_code == 503


class TestChatPathSharedWithFrontendRoute:
    """프론트 화면 주소도 `/chat`이다. POST는 API로, GET은 화면(index.html)으로 가야 한다."""

    async def test_get_serves_spa_and_post_reaches_api(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        user: User,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "index.html").write_text(
            f"<html><head>{SPA_INDEX_MARKER}</head></html>", encoding="utf-8"
        )
        app = ChatApiAppFactory().create(session_factory, user=user)
        # 운영과 같은 순서: 라우터를 먼저 등록하고 정적 파일을 루트에 마운트한다
        app.mount("/", SpaStaticFiles(directory=tmp_path, html=True), name="frontend")

        async for client in client_for(app):
            page = await client.get(CHAT_PATH)
            api = await client.post(CHAT_PATH, json={"request_id": "r1", "message": "안녕"})

        assert page.status_code == 200
        assert SPA_INDEX_MARKER in page.text
        assert api.status_code == 200
        assert api.json()["request_id"] == "r1"
