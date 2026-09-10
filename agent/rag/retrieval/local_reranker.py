"""BGE 교차 인코더로 1차 검색 후보를 로컬 재정렬한다."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

from agent.rag.ports import EvidenceReranker
from agent.rag.schemas import LocalRerankerConfig, RerankRequest, RerankResult


class LocalBgeRerankerV2M3(EvidenceReranker):
    """질문과 각 청크를 함께 읽는 교차 인코더 기반 재정렬기."""

    def __init__(self, config: LocalRerankerConfig) -> None:
        self._config = config
        self._model: CrossEncoder | None = None
        # 동일 PyTorch 모델의 동시 추론이 메모리를 예측 불가능하게 늘리지 않도록 직렬화한다.
        self._inference_lock = asyncio.Lock()

    async def rerank(self, request: RerankRequest) -> RerankResult:
        try:
            async with self._inference_lock:
                # 교차 인코더의 동기 추론을 별도 스레드로 보내 다른 채팅 요청을 막지 않는다.
                return await asyncio.to_thread(self._rerank_blocking, request)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"로컬 리랭커 모델 실행에 실패했습니다 ({self._config.model.value}): {exc}"
            ) from exc

    def _rerank_blocking(self, request: RerankRequest) -> RerankResult:
        model = self._load_model()
        pairs = [[request.query, candidate.chunk.content] for candidate in request.candidates]
        raw_scores = model.predict(
            pairs,
            batch_size=self._config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        scores = cast(Sequence[float], raw_scores)
        if len(scores) != len(request.candidates):
            # 점수와 청크 수가 어긋나면 다른 출처에 관련도 점수를 붙일 수 있으므로 실패시킨다.
            raise ValueError("리랭커 점수 수가 검색 후보 수와 다릅니다.")
        ranked = [
            candidate.model_copy(update={"reranker_score": float(score)})
            for candidate, score in zip(request.candidates, scores, strict=True)
        ]
        ranked.sort(
            key=lambda candidate: (
                -cast(float, candidate.reranker_score),
                -candidate.fused_score,
                candidate.chunk.chunk_id,
            )
        )
        return RerankResult(
            model=self._config.model.value,
            chunks=ranked[: request.limit],
        )

    def _load_model(self) -> CrossEncoder:
        if self._model is None:
            # 운영 조립만으로 모델 파일을 내려받지 않고 첫 검색에서 지연 로드한다.
            from sentence_transformers import CrossEncoder

            device = self._config.device.value if self._config.device is not None else None
            # 모델 카드의 일반 reranker 예시와 같은 512 토큰 입력으로 메모리 사용량을 제한한다.
            self._model = CrossEncoder(
                self._config.model.value,
                device=device,
                cache_folder=self._config.cache_folder,
                trust_remote_code=False,
                local_files_only=self._config.local_files_only,
                max_length=self._config.max_length,
            )
        return self._model
