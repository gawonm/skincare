"""Case와 Evidence reranker가 공유하는 로컬 BGE 교차 인코더 실행기."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

from pydantic import Field, FiniteFloat

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

from agent.rag.schemas import LocalRerankerConfig, RagModel


class RerankerTextPair(RagModel):
    query: str = Field(min_length=1)
    document: str = Field(min_length=1)


class CrossEncoderScoringRequest(RagModel):
    pairs: list[RerankerTextPair] = Field(min_length=1)


class CrossEncoderScoringResult(RagModel):
    model: str = Field(min_length=1)
    scores: list[FiniteFloat] = Field(min_length=1)


class LocalBgeCrossEncoderScorer:
    """한 모델 인스턴스를 공유하면서 동시 GPU 추론은 직렬화한다."""

    def __init__(self, config: LocalRerankerConfig) -> None:
        self._config = config
        self._model: CrossEncoder | None = None
        self._inference_lock = asyncio.Lock()

    async def score(self, request: CrossEncoderScoringRequest) -> CrossEncoderScoringResult:
        try:
            async with self._inference_lock:
                return await asyncio.to_thread(self._score_blocking, request)
        except (OSError, RuntimeError, ValueError) as error:
            raise RuntimeError(
                f"로컬 리랭커 모델 실행에 실패했습니다 ({self._config.model.value}): {error}"
            ) from error

    def _score_blocking(
        self,
        request: CrossEncoderScoringRequest,
    ) -> CrossEncoderScoringResult:
        model = self._load_model()
        raw_scores = model.predict(
            [[pair.query, pair.document] for pair in request.pairs],
            batch_size=self._config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        scores = [float(score) for score in cast(Sequence[float], raw_scores)]
        if len(scores) != len(request.pairs):
            raise ValueError("리랭커 점수 수가 입력 문서 수와 다릅니다.")
        return CrossEncoderScoringResult(
            model=self._config.model.value,
            scores=scores,
        )

    def _load_model(self) -> CrossEncoder:
        if self._model is None:
            # 조립 시 다운로드하지 않고 첫 Case 또는 Evidence rerank에서 한 번만 로드한다.
            from sentence_transformers import CrossEncoder

            device = self._config.device.value if self._config.device is not None else None
            self._model = CrossEncoder(
                self._config.model.value,
                device=device,
                cache_folder=self._config.cache_folder,
                trust_remote_code=False,
                local_files_only=self._config.local_files_only,
                max_length=self._config.max_length,
            )
        return self._model
