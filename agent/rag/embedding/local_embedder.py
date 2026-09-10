"""BGE-M3를 프로세스 안에서 실행하는 비동기 임베딩 어댑터."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from agent.rag.ports import TextEmbedder
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingVector,
    LocalEmbeddingConfig,
)


class LocalBgeM3Embedder(TextEmbedder):
    """모델 추론은 로컬에서 수행하고 모델 파일만 Hugging Face 캐시를 사용한다."""

    def __init__(self, config: LocalEmbeddingConfig) -> None:
        self._config = config
        self._model: SentenceTransformer | None = None
        # PyTorch 추론을 직렬화해 같은 모델이 여러 워커 스레드에서 동시에 변형되지 않게 한다.
        self._inference_lock = asyncio.Lock()

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        try:
            async with self._inference_lock:
                # 동기식 PyTorch 추론이 LangGraph의 이벤트 루프를 막지 않게 워커 스레드로 보낸다.
                return await asyncio.to_thread(self._embed_blocking, request)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"로컬 임베딩 모델 실행에 실패했습니다 ({self._config.model.value}): {exc}"
            ) from exc

    def _embed_blocking(self, request: EmbeddingRequest) -> EmbeddingResult:
        model = self._load_model()
        raw_vectors = model.encode(
            request.texts,
            batch_size=self._config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        vectors = cast(Sequence[Sequence[float]], raw_vectors)
        if len(vectors) != len(request.texts):
            # 수가 다르면 청크와 벡터가 다른 근거에 저장될 수 있으므로 즉시 중단한다.
            raise ValueError("임베딩 결과 수가 요청한 텍스트 수와 다릅니다.")
        return EmbeddingResult(
            model=self._config.model.value,
            vectors=[
                EmbeddingVector(values=[float(value) for value in vector]) for vector in vectors
            ],
        )

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            # 개발용 fixture까지 무거운 PyTorch를 불러오지 않도록 실제 사용 시점에 import한다.
            from sentence_transformers import SentenceTransformer

            device = self._config.device.value if self._config.device is not None else None
            # 임의 원격 코드를 실행하지 않고 공개 모델 가중치와 표준 구현만 로드한다.
            self._model = SentenceTransformer(
                self._config.model.value,
                device=device,
                cache_folder=self._config.cache_folder,
                trust_remote_code=False,
                local_files_only=self._config.local_files_only,
            )
        return self._model
