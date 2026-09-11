"""설정에서 선택한 임베딩 구현을 조립한다."""

from agent.rag.embedding.local_embedder import LocalBgeM3Embedder
from agent.rag.embedding.openai_embedder import OpenAiTextEmbedder
from agent.rag.ports import TextEmbedder
from agent.rag.schemas import EmbeddingProvider, TextEmbeddingConfig


class TextEmbedderFactory:
    def create(self, config: TextEmbeddingConfig) -> TextEmbedder:
        if config.provider is EmbeddingProvider.OPENAI:
            if config.openai is None:
                # Pydantic 검증 뒤에도 타입 검사기가 None 가능성을 남기므로 경계에서 다시 확인한다.
                raise ValueError("OpenAI 임베딩 설정이 없습니다.")
            return OpenAiTextEmbedder(config.openai)
        if config.provider is EmbeddingProvider.LOCAL:
            return LocalBgeM3Embedder(config.local)
        raise ValueError(f"지원하지 않는 임베딩 제공자입니다: {config.provider}")
