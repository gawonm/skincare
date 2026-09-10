"""로그인 세션 저장소(Redis).

세션은 불투명한 랜덤 토큰이다. 토큰 자체에는 아무 의미가 없고, Redis에서 `user_id`로
교환된다. 그래서 로그아웃은 키 하나 삭제로 끝나고, 계정 정지 같은 즉시 무효화도 쉽다.

SQLAlchemy 세션 저장소가 아니라 Redis지만, "데이터 접근 쿼리는 repositories에 모은다"는
규칙을 그대로 따른다. 클라이언트는 생성자에서 주입받는다.
"""

import json
import secrets
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from redis.asyncio import Redis

# Redis 키 앞에 붙이는 네임스페이스. 다른 용도의 키와 섞이지 않게 한다.
_KEY_PREFIX = "session:"
# 토큰 엔트로피(바이트). 32바이트면 URL-safe base64로 약 43자가 되고 추측이 사실상 불가능하다.
_TOKEN_NBYTES = 32


class SessionRecord(BaseModel):
    """Redis에 저장하는 세션 본문."""

    user_id: UUID
    created_at: datetime


class SessionRepository:
    """Redis에 로그인 세션을 만들고 조회하고 지운다."""

    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _key(token: str) -> str:
        return f"{_KEY_PREFIX}{token}"

    async def create(self, user_id: UUID) -> str:
        """새 세션을 만들고 클라이언트에 내려줄 토큰을 돌려준다."""
        token = secrets.token_urlsafe(_TOKEN_NBYTES)
        record = SessionRecord(user_id=user_id, created_at=datetime.now(UTC))
        await self._redis.set(
            self._key(token),
            record.model_dump_json(),
            ex=self._ttl_seconds,
        )
        return token

    async def get(self, token: str) -> SessionRecord | None:
        """토큰에 해당하는 세션을 읽는다. 없거나 만료됐으면 None.

        값이 남아 있는데 형식이 깨진 경우는 저장 로직 버그이거나 외부 조작이므로 숨기지
        않고 올린다.
        """
        raw = await self._redis.get(self._key(token))
        if raw is None:
            return None
        try:
            return SessionRecord.model_validate_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            raise RuntimeError(
                f"세션 값을 해석할 수 없습니다(token 앞 8자={token[:8]}): {e}"
            ) from e

    async def delete(self, token: str) -> None:
        """로그아웃. 키가 이미 없어도 조용히 넘어간다(멱등)."""
        await self._redis.delete(self._key(token))
