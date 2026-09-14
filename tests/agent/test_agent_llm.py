"""로컬 LLM(Ollama/Local) 및 OpenAI 설정과 조립 계약 검증."""

import pytest
from pydantic import SecretStr, ValidationError

from agent.adapters import (
    FixtureEvidenceRetriever,
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
from agent.rag.generation.openai_generator import (
    ChatModelClaimGenerator,
    ClaimGeneratorFactory,
    OpenAiClaimGenerator,
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
from langgraph.checkpoint.memory import InMemorySaver


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

    def test_factory_creates_claim_generator(self) -> None:
        config = ChatModelConfig(
            provider=LlmProvider.OLLAMA,
            local=LocalChatConfig(
                base_url="http://localhost:11434/v1",
                model="qwen 3.5:9B",
            ),
        )
        generator = ClaimGeneratorFactory().create(config)
        assert isinstance(generator, ChatModelClaimGenerator)

    def test_backward_compatibility_wrapper_creates_valid_instance(self) -> None:
        openai_config = OpenAiChatConfig(
            api_key=SecretStr("test-key"),
            model=OpenAiChatModel.GPT_4O_MINI,
        )
        llm = OpenAiLlmClient(openai_config)
        generator = OpenAiClaimGenerator(openai_config)
        assert isinstance(llm, ChatModelLlmClient)
        assert isinstance(generator, ChatModelClaimGenerator)

    def test_production_agent_config_backward_compatibility(self) -> None:
        openai_config = OpenAiChatConfig(
            api_key=SecretStr("test-key"),
            model=OpenAiChatModel.GPT_4O_MINI,
        )
        config = ProductionAgentConfig(
            openai=openai_config,
            embedding=TextEmbeddingConfig(
                provider=EmbeddingProvider.OPENAI,
                openai=OpenAiEmbeddingConfig(api_key=SecretStr("test-key")),
            ),
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
        from core.config import AgentSettings, LlmChatSettings, LlmProvider as CoreLlmProvider, LocalChatSettings

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

    def test_assembler_creates_production_config_with_ollama_and_openai_embedding(self) -> None:
        from backend.services.agent_configuration import AgentConfigurationAssembler
        from core.config import (
            AgentSettings,
            EmbeddingSettings,
            LlmChatSettings,
            LlmProvider as CoreLlmProvider,
            LocalChatSettings,
            OpenAiConfig,
            RagRetrievalSettings,
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
        prod_config = AgentConfigurationAssembler().create(openai=openai_config, agent=agent_settings)
        assert prod_config.chat.provider is LlmProvider.OLLAMA
        assert prod_config.chat.active_model() == "qwen 3.5:9B"
        assert prod_config.embedding.output_dimensions() == 1536

