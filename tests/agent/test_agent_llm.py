"""로컬 LLM(Ollama/Local) 및 OpenAI 설정과 조립 계약 검증."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr, ValidationError

from agent.adapters import (
    FixtureClaimRetriever,
    FixtureIngredientRepository,
    FixtureProductRepository,
    FixtureProductTaxonomy,
    FixtureRoutinePlanner,
    InMemoryChatHistoryRepository,
)
from agent.factory import (
    ProductionAgentConfig,
    ProductionAgentDependencies,
    ProductionAgentFactory,
)
from agent.llm import ChatModelLlmClient, LlmClientFactory, OpenAiLlmClient
from agent.rag.generation.evidence_statement_generator import (
    ChatModelEvidenceStatementGenerator,
    EvidenceStatementGeneratorFactory,
    OpenAiEvidenceStatementGenerator,
)
from agent.rag.ports import HybridSearchBackend
from agent.rag.schemas import (
    ChatModelConfig,
    EmbeddingProvider,
    HybridSearchRequest,
    HybridSearchResult,
    LlmProvider,
    LocalChatConfig,
    LocalEmbeddingConfig,
    LookupStatus,
    OpenAiChatConfig,
    OpenAiChatModel,
    OpenAiEmbeddingConfig,
    RagRetrievalPolicy,
    TextEmbeddingConfig,
)


class DummyHybridSearchBackend(HybridSearchBackend):
    async def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        return HybridSearchResult(status=LookupStatus.NO_RESULTS)


class TestAgentLlmConfigAndAssembly:
    def test_chat_config_requires_openai_config_when_openai_provider(self) -> None:
        with pytest.raises(ValidationError, match="OpenAI 채팅 설정이 필요합니다"):
            ChatModelConfig(provider=LlmProvider.OPENAI, openai=None)

    def test_chat_config_defaults_for_ollama(self) -> None:
        config = ChatModelConfig(
            provider=LlmProvider.OLLAMA,
            local=LocalChatConfig(
                base_url="http://localhost:11434/v1",
                model="qwen 3.5:9B",
            ),
        )
        assert config.provider is LlmProvider.OLLAMA
        assert config.active_model() == "qwen 3.5:9B"
        assert config.local.base_url == "http://localhost:11434/v1"

    def test_factory_creates_chat_model_client(self) -> None:
        config = ChatModelConfig(
            provider=LlmProvider.OLLAMA,
            local=LocalChatConfig(
                base_url="http://localhost:11434/v1",
                model="qwen 3.5:9B",
            ),
        )
        client = LlmClientFactory().create(config)
        assert isinstance(client, ChatModelLlmClient)

    def test_factory_creates_evidence_statement_generator(self) -> None:
        config = ChatModelConfig(
            provider=LlmProvider.OLLAMA,
            local=LocalChatConfig(
                base_url="http://localhost:11434/v1",
                model="qwen 3.5:9B",
            ),
        )
        generator = EvidenceStatementGeneratorFactory().create(config)
        assert isinstance(generator, ChatModelEvidenceStatementGenerator)

    def test_backward_compatibility_wrapper_creates_valid_instance(self) -> None:
        openai_config = OpenAiChatConfig(
            api_key=SecretStr("test-key"),
            model=OpenAiChatModel.GPT_4O_MINI,
        )
        llm = OpenAiLlmClient(openai_config)
        generator = OpenAiEvidenceStatementGenerator(openai_config)
        assert isinstance(llm, ChatModelLlmClient)
        assert isinstance(generator, ChatModelEvidenceStatementGenerator)

    def test_production_agent_config_rejects_openai_embedding(self) -> None:
        openai_config = OpenAiChatConfig(
            api_key=SecretStr("test-key"),
            model=OpenAiChatModel.GPT_4O_MINI,
        )
        with pytest.raises(ValidationError, match="BGE-M3"):
            ProductionAgentConfig(
                openai=openai_config,
                embedding=TextEmbeddingConfig(
                    provider=EmbeddingProvider.OPENAI,
                    openai=OpenAiEmbeddingConfig(api_key=SecretStr("test-key")),
                ),
                retrieval_policy=RagRetrievalPolicy(free_text_min_vector_similarity=0.45),
            )

    def test_production_agent_config_keeps_openai_chat_with_bge_m3(self) -> None:
        openai_config = OpenAiChatConfig(
            api_key=SecretStr("test-key"),
            model=OpenAiChatModel.GPT_4O_MINI,
        )
        config = ProductionAgentConfig(
            openai=openai_config,
            embedding=TextEmbeddingConfig(provider=EmbeddingProvider.LOCAL),
            retrieval_policy=RagRetrievalPolicy(free_text_min_vector_similarity=0.45),
        )
        assert config.chat is not None
        assert config.chat.provider is LlmProvider.OPENAI
        assert config.chat.active_model() == "gpt-4o-mini"

    def test_production_agent_factory_assembles_with_ollama_and_local_embedding(self) -> None:
        config = ProductionAgentConfig(
            chat=ChatModelConfig(
                provider=LlmProvider.OLLAMA,
                local=LocalChatConfig(
                    base_url="http://localhost:11434/v1",
                    model="qwen 3.5:9B",
                ),
            ),
            embedding=TextEmbeddingConfig(
                provider=EmbeddingProvider.LOCAL,
                local=LocalEmbeddingConfig(),
            ),
            retrieval_policy=RagRetrievalPolicy(free_text_min_vector_similarity=0.5),
        )
        dependencies = ProductionAgentDependencies(
            history=InMemoryChatHistoryRepository(),
            products=FixtureProductRepository(),
            product_taxonomy=FixtureProductTaxonomy().create(),
            ingredients=FixtureIngredientRepository(),
            routine_planner=FixtureRoutinePlanner(),
            claim_retriever=FixtureClaimRetriever(),
            search_backend=DummyHybridSearchBackend(),
            checkpointer=InMemorySaver(),
        )
        app = ProductionAgentFactory().create(dependencies, config)
        assert app.service is not None
        assert app.embedder is not None
        assert app.evidence_retriever is not None


class TestAgentConfigurationAssembler:
    def test_assembler_creates_chat_with_ollama_provider(self) -> None:
        from backend.services.agent_configuration import AgentConfigurationAssembler
        from core.config import AgentSettings, LlmChatSettings, LocalChatSettings
        from core.config import LlmProvider as CoreLlmProvider

        agent_settings = AgentSettings(
            chat=LlmChatSettings(
                provider=CoreLlmProvider.OLLAMA,
                local=LocalChatSettings(
                    base_url="http://localhost:11434/v1",
                    model="qwen 3.5:9B",
                ),
            )
        )
        chat_config = AgentConfigurationAssembler().create_chat(openai=None, agent=agent_settings)
        assert chat_config.provider is LlmProvider.OLLAMA
        assert chat_config.active_model() == "qwen 3.5:9B"
        assert chat_config.local.base_url == "http://localhost:11434/v1"

    def test_assembler_legacy_openai_embedding_is_rejected_by_agent_contract(self) -> None:
        from backend.services.agent_configuration import AgentConfigurationAssembler
        from core.config import (
            AgentSettings,
            EmbeddingSettings,
            LlmChatSettings,
            LocalChatSettings,
            OpenAiConfig,
            RagRetrievalSettings,
        )
        from core.config import (
            LlmProvider as CoreLlmProvider,
        )

        openai_config = OpenAiConfig(api_key="test-key")
        agent_settings = AgentSettings(
            chat=LlmChatSettings(
                provider=CoreLlmProvider.OLLAMA,
                local=LocalChatSettings(
                    base_url="http://localhost:11434/v1",
                    model="qwen 3.5:9B",
                ),
            ),
            embedding=EmbeddingSettings(openai_dimensions=1536),
            retrieval=RagRetrievalSettings(free_text_min_vector_similarity=0.45),
        )
        with pytest.raises(ValidationError, match="BGE-M3"):
            AgentConfigurationAssembler().create(openai=openai_config, agent=agent_settings)

