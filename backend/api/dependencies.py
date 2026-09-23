"""`api/` 엔드포인트가 쓰는 FastAPI 의존성.

여기서 계층을 조립한다. 요청마다 DB 세션을 하나 열고, 그 세션을 공유하는 리포지토리와
서비스를 만들어 넘긴다. 엔드포인트 함수는 이 결과만 받아 쓴다.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from agent.service import ChatService
from backend.repositories.session import SessionRepository
from backend.repositories.user import UserRepository
from backend.services.auth import AuthService
from backend.services.chat_room import ChatRoomService
from backend.services.chat_turn import ChatTurnService
from backend.services.product_query_service import ProductQueryService
from backend.services.security import PasswordHasher
from core.config import settings
from models import User

# lifespan이 Agent `ChatService`를 `app.state`에 올려 둘 때 쓰는 이름. 엔드포인트와 조립 코드가
# 같은 문자열을 각자 적다가 어긋나지 않게 한곳에 둔다.
AGENT_CHAT_SERVICE_STATE_NAME = "agent_chat_service"

# argon2 파라미터만 들고 있어 상태가 없다. 요청마다 새로 만들 이유가 없어 한 번만 만든다.
_password_hasher = PasswordHasher()


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """요청 1개당 SQLAlchemy 세션 1개. 예외가 나면 롤백하고, 끝나면 반드시 닫는다."""
    database = request.app.state.database
    session: AsyncSession = database.session_factory()
    try:
        yield session
    except Exception:
        # 커밋 전에 터진 변경이 다음 요청으로 새지 않도록 명시적으로 되돌린다.
        await session.rollback()
        raise
    finally:
        await session.close()


def get_redis(request: Request) -> Redis:
    """lifespan에서 만들어 둔 Redis 클라이언트를 그대로 쓴다. 요청마다 연결을 열지 않는다."""
    return request.app.state.redis.client


# 엔드포인트 시그니처가 길어지지 않도록 자주 쓰는 의존성에 별칭을 둔다.
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def get_auth_service(session: SessionDep, redis: RedisDep) -> AuthService:
    """DB 세션과 Redis 위에 리포지토리·해셔를 얹어 `AuthService`를 만든다."""
    return AuthService(
        session=session,
        user_repository=UserRepository(session),
        session_repository=SessionRepository(redis, ttl_seconds=settings.auth.session_ttl_seconds),
        password_hasher=_password_hasher,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(request: Request, auth_service: AuthServiceDep) -> User:
    """세션 쿠키로 로그인 사용자를 확인한다. 쿠키가 없거나 무효면 401을 던진다."""
    token = request.cookies.get(settings.auth.cookie_name)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )
    user = await auth_service.get_current_user(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요.",
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_agent_chat_service(request: Request) -> ChatService:
    """앱 시작 때 조립된 Agent `ChatService`. 아직 조립되지 않았으면 503을 던진다."""
    service = getattr(request.app.state, AGENT_CHAT_SERVICE_STATE_NAME, None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI 채팅이 아직 준비되지 않았습니다.",
        )
    return service


AgentChatServiceDep = Annotated[ChatService, Depends(get_agent_chat_service)]


def get_chat_turn_service(request: Request, agent: AgentChatServiceDep) -> ChatTurnService:
    """방 준비 서비스와 Agent를 묶어 채팅 한 턴을 처리하는 서비스를 만든다."""
    database = request.app.state.database
    return ChatTurnService(rooms=ChatRoomService(database.session_factory), agent=agent)


ChatTurnServiceDep = Annotated[ChatTurnService, Depends(get_chat_turn_service)]


def get_product_query_service(session: SessionDep) -> ProductQueryService:
    return ProductQueryService(session)


ProductQueryServiceDep = Annotated[ProductQueryService, Depends(get_product_query_service)]
