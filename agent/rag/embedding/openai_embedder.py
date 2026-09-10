"""설정 파일과 DB를 읽지 않는 비동기 임베딩 어댑터."""

from langchain_openai import OpenAIEmbeddings

from agent.rag.ports import TextEmbedder
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingVector,
    OpenAiModelConfig,
)


class OpenAiEmbedder(TextEmbedder):
    """OpenAI 임베딩 API를 호출해 텍스트를 벡터로 변환하는 어댑터.

    환경설정 파일이나 DB를 직접 읽지 않고 설정 객체를 주입받아,
    테스트 환경과 운영 환경에서 동일한 클래스를 재사용할 수 있게 한다.
    """

    def __init__(self, config: OpenAiModelConfig) -> None:
        self._model = config.model
        # SecretStr을 사용해 로그 출력이나 직렬화 과정에서 API 키가 평문 노출되는 것을 방지한다
        self._client = OpenAIEmbeddings(
            api_key=config.api_key.get_secret_value(),
            model=config.model,
            request_timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        # FastAPI/LangGraph의 비동기 이벤트 루프가 외부 HTTP 호출로 블로킹되지 않도록 비동기 메서드를 사용한다
        vectors = await self._client.aembed_documents(request.texts)

        # 텍스트와 벡터 수가 일치하지 않으면 DB 적재 시 청크와 임베딩이 어긋나 잘못된 근거가 매핑되므로 즉시 중단한다
        if len(vectors) != len(request.texts):
            raise ValueError("임베딩 응답 수가 요청한 텍스트 수와 다릅니다.")

        # 원시 float 리스트 대신 Pydantic 모델로 감싸 상위 계층과의 타입 계약을 유지한다
        return EmbeddingResult(
            model=self._model,
            vectors=[EmbeddingVector(values=vector) for vector in vectors],
        )
