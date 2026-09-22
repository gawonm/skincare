"""Agent 운영 조립(`ChatAgentAssembler`)과 앱 시작 때의 조립 실패 정책을 검증한다.

모델 파일은 첫 사용 때 불러오므로 조립만으로는 BGE-M3나 리랭커를 내려받지 않는다. 그래서 실제
OpenAI 호출이나 모델 로드 없이 조립 자체가 성공하는지 확인할 수 있다. 상품 분류는 설정된 DB의
`product` 테이블에서 읽으므로 상품이 적재된 DB가 필요하다.
"""

import logging

import pytest

from agent.service import ChatService
from backend.main import Application
from backend.services.agent_assembly import ChatAgentAssembler
from core.config import (
    AgentSettings,
    EmbeddingProvider,
    EmbeddingSettings,
    OpenAiConfig,
    RagRetrievalSettings,
    settings,
)
from core.database import Database

TEST_API_KEY = "test-key-not-real"
TEST_ANNOTATION_VERSION = "test-annotation-v1"
TEST_MIN_SIMILARITY = 0.5


class AssemblerInputs:
    """조립에 필요한 설정을 만든다."""

    def openai(self) -> OpenAiConfig:
        return OpenAiConfig(api_key=TEST_API_KEY)

    def agent(self, provider: EmbeddingProvider) -> AgentSettings:
        # BGE-M3는 검증된 유사도 임계값을 설정으로 받아야 조립된다. claim_annotation_version은
        # 오프라인 Claim 경로 전용이라 P3 기본 경로(Case 검색) 조립에는 없어도 된다.
        return AgentSettings(
            embedding=EmbeddingSettings(provider=provider),
            retrieval=RagRetrievalSettings(free_text_min_vector_similarity=TEST_MIN_SIMILARITY),
        )


class TestChatAgentAssembler:
    inputs = AssemblerInputs()

    async def test_local_embedding_settings_assemble_a_chat_service(self) -> None:
        database = Database(settings.database)
        try:
            service = await ChatAgentAssembler(
                database.session_factory,
                self.inputs.openai(),
                self.inputs.agent(EmbeddingProvider.LOCAL),
            ).create()
        finally:
            await database.dispose()

        assert isinstance(service, ChatService)

    async def test_openai_embedding_is_rejected_with_dimension_message(self) -> None:
        # 운영 2-Layer RAG는 BGE-M3(1024차원) 저장소를 쓰므로 OpenAI(1536차원) 임베딩을 고르면
        # 모델을 불러오기 전에 차원 불일치로 막아야 한다.
        database = Database(settings.database)
        try:
            assembler = ChatAgentAssembler(
                database.session_factory,
                self.inputs.openai(),
                self.inputs.agent(EmbeddingProvider.OPENAI),
            )
            with pytest.raises(RuntimeError, match="차원"):
                await assembler.create()
        finally:
            await database.dispose()

    async def test_missing_openai_block_is_rejected(self) -> None:
        database = Database(settings.database)
        try:
            assembler = ChatAgentAssembler(
                database.session_factory, None, self.inputs.agent(EmbeddingProvider.LOCAL)
            )
            with pytest.raises(RuntimeError, match="openai"):
                await assembler.create()
        finally:
            await database.dispose()


class StubService:
    """조립이 성공했을 때 앱 상태에 올라가는지만 보려는 대역."""


class StubAssembler:
    def __init__(self, error: Exception | None) -> None:
        self._error = error

    async def create(self) -> StubService:
        if self._error is not None:
            raise self._error
        return StubService()


class ApplicationWithStubAssembler(Application):
    def __init__(self, error: Exception | None) -> None:
        super().__init__()
        self._stub_error = error

    def _create_agent_assembler(self, database: Database) -> StubAssembler:  # type: ignore[override]
        return StubAssembler(self._stub_error)


class TestAgentAssemblyAtStartup:
    def _database(self) -> Database:
        return Database(settings.database)

    async def test_successful_assembly_is_stored_on_app_state(self) -> None:
        from backend.api.dependencies import AGENT_CHAT_SERVICE_STATE_NAME

        application = ApplicationWithStubAssembler(error=None)
        database = self._database()
        try:
            await application._assemble_agent(application.app, database)
        finally:
            await database.dispose()

        service = getattr(application.app.state, AGENT_CHAT_SERVICE_STATE_NAME)
        assert isinstance(service, StubService)

    @pytest.mark.parametrize("error", [RuntimeError("설정 오류"), ValueError("값 오류")])
    async def test_failed_assembly_keeps_server_up_and_logs_the_cause(
        self, error: Exception, caplog: pytest.LogCaptureFixture
    ) -> None:
        from backend.api.dependencies import AGENT_CHAT_SERVICE_STATE_NAME

        application = ApplicationWithStubAssembler(error=error)
        database = self._database()
        try:
            with caplog.at_level(logging.ERROR):
                await application._assemble_agent(application.app, database)
        finally:
            await database.dispose()

        assert getattr(application.app.state, AGENT_CHAT_SERVICE_STATE_NAME, None) is None
        # 원인 예외는 메시지가 아니라 로그의 예외 정보(traceback)로 남는다
        assert any(
            record.exc_info is not None and record.exc_info[1] is error for record in caplog.records
        )

    async def test_unexpected_error_types_are_not_swallowed(self) -> None:
        application = ApplicationWithStubAssembler(error=KeyError("예상 밖 오류"))
        database = self._database()
        try:
            with pytest.raises(KeyError):
                await application._assemble_agent(application.app, database)
        finally:
            await database.dispose()
