"""`config.yaml` 설정을 Agent 소유 운영 설정으로 변환한다."""

from pydantic import SecretStr

from agent.factory import ProductionAgentConfig
from agent.rag.schemas import (
    EmbeddingProvider,
    LocalEmbeddingConfig,
    LocalEmbeddingModel,
    LocalRerankerConfig,
    LocalRerankerModel,
    OpenAiChatConfig,
    OpenAiChatModel,
    OpenAiEmbeddingConfig,
    OpenAiEmbeddingModel,
    RagRetrievalPolicy,
    TextEmbeddingConfig,
)
from agent.rag.schemas import (
    LocalModelDevice as AgentLocalModelDevice,
)
from core.config import AgentSettings, OpenAiConfig
from core.config import EmbeddingProvider as CoreEmbeddingProvider
from core.config import LocalModelDevice as CoreLocalModelDevice


class AgentConfigurationAssembler:
    """공용 설정 계층과 Agent 계층이 서로의 모델을 직접 소유하지 않게 경계를 변환한다."""

    def create(
        self,
        openai: OpenAiConfig | None,
        agent: AgentSettings,
    ) -> ProductionAgentConfig:
        if openai is None:
            raise RuntimeError("config.yaml에 openai 블록이 없어 Agent를 조립할 수 없습니다.")
        threshold = agent.retrieval.free_text_min_vector_similarity
        if threshold is None:
            embedding_model = (
                agent.embedding.openai_model.value
                if agent.embedding.provider is CoreEmbeddingProvider.OPENAI
                else agent.embedding.model.value
            )
            raise RuntimeError(
                "config.yaml의 agent.retrieval.free_text_min_vector_similarity를 "
                f"{embedding_model} 검증값으로 설정해야 합니다."
            )
        return ProductionAgentConfig(
            openai=OpenAiChatConfig(
                api_key=SecretStr(openai.api_key),
                model=OpenAiChatModel(openai.chat_model.value),
                timeout_seconds=openai.timeout_seconds,
                max_retries=openai.max_retries,
            ),
            embedding=self.create_embedding(openai, agent),
            reranker=LocalRerankerConfig(
                model=LocalRerankerModel(agent.reranker.model.value),
                device=self._device(agent.reranker.device),
                batch_size=agent.reranker.batch_size,
                max_length=agent.reranker.max_length,
                cache_folder=agent.reranker.cache_folder,
                local_files_only=agent.reranker.local_files_only,
            ),
            retrieval_policy=RagRetrievalPolicy(
                free_text_min_vector_similarity=threshold,
                rrf_k=agent.retrieval.rrf_k,
                rerank_candidate_limit=agent.retrieval.rerank_candidate_limit,
            ),
        )

    def create_embedding(
        self,
        openai: OpenAiConfig | None,
        agent: AgentSettings,
    ) -> TextEmbeddingConfig:
        openai_embedding = self._openai_embedding(openai, agent)
        return TextEmbeddingConfig(
            provider=EmbeddingProvider(agent.embedding.provider.value),
            openai=openai_embedding,
            local=LocalEmbeddingConfig(
                model=LocalEmbeddingModel(agent.embedding.model.value),
                device=self._device(agent.embedding.device),
                batch_size=agent.embedding.batch_size,
                cache_folder=agent.embedding.cache_folder,
                local_files_only=agent.embedding.local_files_only,
            ),
        )

    def _openai_embedding(
        self,
        openai: OpenAiConfig | None,
        agent: AgentSettings,
    ) -> OpenAiEmbeddingConfig | None:
        if agent.embedding.provider is CoreEmbeddingProvider.LOCAL:
            return None
        if openai is None:
            raise RuntimeError("OpenAI 임베딩을 선택했지만 config.yaml에 openai 블록이 없습니다.")
        return OpenAiEmbeddingConfig(
            api_key=SecretStr(openai.api_key),
            model=OpenAiEmbeddingModel(agent.embedding.openai_model.value),
            dimensions=agent.embedding.openai_dimensions,
            batch_size=agent.embedding.openai_batch_size,
            timeout_seconds=openai.timeout_seconds,
            max_retries=openai.max_retries,
        )

    def _device(self, device: CoreLocalModelDevice | None) -> AgentLocalModelDevice | None:
        if device is None:
            return None
        return AgentLocalModelDevice(device.value)
