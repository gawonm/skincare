"""텍스트를 OpenAI 임베딩 모델로 벡터화한다.

임베딩 모델을 바꾸면 기존 벡터는 못 쓴다(전체 재임베딩 필요) - 그래서 벡터마다
`embedding_model`을 함께 저장해서 나중에 어떤 모델로 만들었는지 구분할 수 있게 한다.

대량 적재(NIA Q&A 등) 중 분당 토큰 한도(TPM)에 걸리는 `RateLimitError`가 실제로
발생했다(2026-09-09) - OpenAI가 응답에 넣어준 대기 시간만큼 쉬었다가 같은 배치를
다시 보낸다. 이 에러를 조용히 삼키지 않고, 최대 재시도 횟수를 넘기면 그대로 올린다.
"""

import re
import time

from langchain_openai import OpenAIEmbeddings
from openai import RateLimitError

from agent.rag.schemas import EmbeddedChunk, RagChunkDraft

# OpenAI 임베딩 API 한 번에 보내는 텍스트 개수. 너무 크면 요청 하나가 실패했을 때
# 전부 다시 보내야 하고, 너무 작으면 요청 횟수가 늘어나 느려진다.
_EMBEDDING_BATCH_SIZE = 100

# 429 응답에 대기 시간이 없을 때 쓰는 기본 대기(초)와 최대 재시도 횟수.
_DEFAULT_RETRY_DELAY_SECONDS = 5.0
_MAX_RETRY_ATTEMPTS = 5

_RETRY_AFTER_PATTERN = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)


class OpenAiEmbedder:
    """`RagChunkDraft` 목록을 임베딩해 `EmbeddedChunk` 목록으로 만든다."""

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = OpenAIEmbeddings(api_key=api_key, model=model)

    def embed(self, drafts: list[RagChunkDraft]) -> list[EmbeddedChunk]:
        embedded: list[EmbeddedChunk] = []
        for start in range(0, len(drafts), _EMBEDDING_BATCH_SIZE):
            batch = drafts[start : start + _EMBEDDING_BATCH_SIZE]
            vectors = self._embed_batch_with_retry([draft.content for draft in batch])
            embedded.extend(
                EmbeddedChunk(draft=draft, vector=tuple(vector), embedding_model=self._model)
                for draft, vector in zip(batch, vectors, strict=True)
            )
        return embedded

    def embed_query(self, query_text: str) -> tuple[float, ...]:
        return tuple(self._client.embed_query(query_text))

    def _embed_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                return self._client.embed_documents(texts)
            except RateLimitError as error:
                if attempt == _MAX_RETRY_ATTEMPTS:
                    raise RuntimeError(
                        f"OpenAI 임베딩 API 속도 제한을 {_MAX_RETRY_ATTEMPTS}번 재시도 후에도 "
                        f"넘지 못했습니다: {error}"
                    ) from error
                time.sleep(self._retry_delay_seconds(error))
        raise AssertionError(
            "도달할 수 없는 코드: 루프가 재시도 횟수 안에서 반환하거나 예외를 올린다"
        )

    def _retry_delay_seconds(self, error: RateLimitError) -> float:
        match = _RETRY_AFTER_PATTERN.search(str(error))
        if match is None:
            return _DEFAULT_RETRY_DELAY_SECONDS
        # OpenAI가 알려준 대기 시간에 여유를 조금 더 둔다.
        return float(match.group(1)) + 1.0
