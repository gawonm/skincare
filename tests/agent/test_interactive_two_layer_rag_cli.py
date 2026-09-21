"""실제 Agent CLI가 공용 설정의 DB를 우회하지 않는지 검증한다."""

from sqlalchemy.engine import make_url

from core.config import settings
from tests.agent.interactive_two_layer_rag_cli import ConfiguredDatabaseFactory


class TestConfiguredDatabaseFactory:
    async def test_uses_database_url_from_config_yaml(self) -> None:
        factory = ConfiguredDatabaseFactory()
        database = factory.create()

        try:
            configured_url = make_url(settings.database.url)
            assert database.engine.url == configured_url
            assert factory.database_name() == configured_url.database
        finally:
            await database.dispose()

