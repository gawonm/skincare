"""운영 임베딩 선택과 OpenAI 벡터 계약을 외부 호출 없이 검증한다."""

import pytest
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr, ValidationError

from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.embedding.local_embedder import LocalBgeM3Embedder
from agent.rag.embedding.openai_embedder import OpenAiTextEmbedder
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    DEFAULT_OPENAI_EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
    EmbeddingRequest,
    LocalEmbeddingConfig,
    OpenAiEmbeddingConfig,
    TextEmbeddingConfig,
)


class OpenAiEmbeddingApiStub:
    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions
        self.requests: list[list[str]] = []

    async def aembed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.requests.append(texts)
        return [[float(index)] * self._dimensions for index, _ in enumerate(texts, start=1)]


class TestAgentEmbedding:
    async def test_openai_embedder_returns_1536_dimension_vectors_with_model_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub = OpenAiEmbeddingApiStub(DEFAULT_OPENAI_EMBEDDING_DIMENSIONS)
        monkeypatch.setattr(OpenAIEmbeddings, "aembed_documents", stub.aembed_documents)
        embedder = OpenAiTextEmbedder(OpenAiEmbeddingConfig(api_key=SecretStr("test-key")))

        result = await embedder.embed(EmbeddingRequest(texts=["첫 문서", "둘째 문서"]))

        assert stub.requests == [["첫 문서", "둘째 문서"]]
        assert result.model == "text-embedding-3-small"
        assert len(result.vectors) == 2
        assert all(
            len(vector.values) == DEFAULT_OPENAI_EMBEDDING_DIMENSIONS
            for vector in result.vectors
        )

    async def test_openai_embedder_rejects_dimension_mismatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub = OpenAiEmbeddingApiStub(DEFAULT_OPENAI_EMBEDDING_DIMENSIONS - 1)
        monkeypatch.setattr(OpenAIEmbeddings, "aembed_documents", stub.aembed_documents)
        embedder = OpenAiTextEmbedder(OpenAiEmbeddingConfig(api_key=SecretStr("test-key")))

        with pytest.raises(ValueError, match="결과 차원이 설정과 다릅니다"):
            await embedder.embed(EmbeddingRequest(texts=["문서"]))

    def test_factory_selects_openai_or_local_implementation(self) -> None:
        factory = TextEmbedderFactory()
        openai = factory.create(
            TextEmbeddingConfig(
                provider=EmbeddingProvider.OPENAI,
                openai=OpenAiEmbeddingConfig(api_key=SecretStr("test-key")),
            )
        )
        local = factory.create(
            TextEmbeddingConfig(
                provider=EmbeddingProvider.LOCAL,
                local=LocalEmbeddingConfig(),
            )
        )

        assert isinstance(openai, OpenAiTextEmbedder)
        assert isinstance(local, LocalBgeM3Embedder)

    def test_embedding_config_reports_provider_output_dimensions(self) -> None:
        openai = TextEmbeddingConfig(
            provider=EmbeddingProvider.OPENAI,
            openai=OpenAiEmbeddingConfig(api_key=SecretStr("test-key")),
        )
        local = TextEmbeddingConfig(provider=EmbeddingProvider.LOCAL)

        assert openai.output_dimensions() == DEFAULT_OPENAI_EMBEDDING_DIMENSIONS
        assert local.output_dimensions() == BGE_M3_EMBEDDING_DIMENSIONS

    def test_openai_provider_requires_api_configuration(self) -> None:
        with pytest.raises(ValidationError, match="OpenAI 임베딩 설정이 필요합니다"):
            TextEmbeddingConfig(provider=EmbeddingProvider.OPENAI)
