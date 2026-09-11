"""OpenAI Embeddings API를 현재 비동기 RAG 계약에 연결한다."""

from langchain_openai import OpenAIEmbeddings
from openai import OpenAIError

from agent.rag.ports import TextEmbedder
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingVector,
    OpenAiEmbeddingConfig,
)


class OpenAiTextEmbedder(TextEmbedder):
    """출력 차원을 명시해 기존 pgvector 컬럼과 같은 벡터만 반환한다."""

    def __init__(self, config: OpenAiEmbeddingConfig) -> None:
        self._config = config
        self._client = OpenAIEmbeddings(
            api_key=config.api_key,
            model=config.model.value,
            dimensions=config.dimensions,
            chunk_size=config.batch_size,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        try:
            raw_vectors = await self._client.aembed_documents(request.texts)
            return self._result(request, raw_vectors)
        except OpenAIError as exc:
            raise RuntimeError(
                f"OpenAI 임베딩 API 호출에 실패했습니다 ({self._config.model.value}): {exc}"
            ) from exc

    def _result(
        self,
        request: EmbeddingRequest,
        raw_vectors: list[list[float]],
    ) -> EmbeddingResult:
        if len(raw_vectors) != len(request.texts):
            # 수가 다르면 청크와 벡터가 다른 근거에 저장될 수 있으므로 즉시 중단한다.
            raise ValueError("임베딩 결과 수가 요청한 텍스트 수와 다릅니다.")
        vectors = [EmbeddingVector(values=vector) for vector in raw_vectors]
        invalid_dimensions = [
            len(vector.values)
            for vector in vectors
            if len(vector.values) != self._config.dimensions
        ]
        if invalid_dimensions:
            raise ValueError(
                "OpenAI 임베딩 결과 차원이 설정과 다릅니다: "
                f"expected={self._config.dimensions}, actual={invalid_dimensions[0]}"
            )
        return EmbeddingResult(model=self._config.model.value, vectors=vectors)
