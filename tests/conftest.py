"""공용 픽스처.

`session` 픽스처는 테스트마다 SAVEPOINT를 만들고 끝나면 롤백한다 - 테스트 코드가 그 안에서
`session.commit()`을 호출해도(재적재 로직이 실제로 그렇게 한다) 바깥 트랜잭션은 커밋되지
않아 로컬 개발 DB에 테스트 데이터가 남지 않는다.
"""

import pytest_asyncio


@pytest_asyncio.fixture
async def session():
    # DB를 쓰지 않는 Agent 단위 테스트가 로컬 config.yaml 유무에 종속되지 않게 지연 import한다.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.config import settings
    from core.database import Database

    database = Database(settings.database)
    try:
        async with database.engine.connect() as connection:
            transaction = await connection.begin()
            session_factory = async_sessionmaker(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            async with session_factory() as session:
                yield session
            await transaction.rollback()
    finally:
        await database.dispose()
