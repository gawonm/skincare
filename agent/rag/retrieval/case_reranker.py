"""BGE 교차 인코더로 NIA Case 후보를 Top-3까지 재정렬한다."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

from agent.rag.case_schemas import CaseRerankRequest, CaseRerankResult
from agent.rag.ports import CaseReranker
from agent.rag.schemas import LocalRerankerConfig


class LocalBgeCaseRerankerV2M3(CaseReranker):
    """질문과 Case 원문을 함께 읽는 로컬 교차 인코더 재정렬기."""

    def __init__(self, config: LocalRerankerConfig) -> None:
        self._config = config
        self._model: CrossEncoder | None = None
        # 같은 PyTorch 모델의 동시 추론이 GPU 메모리를 예측 불가능하게 늘리지 않도록 직렬화한다.
        self._inference_lock = asyncio.Lock()

    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        try:
            async with self._inference_lock:
                # 동기식 CrossEncoder 추론이 다른 채팅 요청의 이벤트 루프를 막지 않게 한다.
                return await asyncio.to_thread(self._rerank_blocking, request)
        except (OSError, RuntimeError, ValueError) as error:
            raise RuntimeError(
                f"NIA Case 리랭커 실행에 실패했습니다 ({self._config.model.value}): {error}"
            ) from error

    def _rerank_blocking(self, request: CaseRerankRequest) -> CaseRerankResult:
        model = self._load_model()
        pairs = [[request.query, candidate.page_content] for candidate in request.candidates]
        raw_scores = model.predict(
            pairs,
            batch_size=self._config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        scores = cast(Sequence[float], raw_scores)
        if len(scores) != len(request.candidates):
            raise ValueError("리랭커 점수 수가 NIA Case 후보 수와 다릅니다.")
        ranked = [
            candidate.model_copy(update={"rerank_score": float(score)})
            for candidate, score in zip(request.candidates, scores, strict=True)
        ]
        ranked.sort(
            key=lambda candidate: (
                -cast(float, candidate.rerank_score),
                -candidate.vector_similarity,
                candidate.case_id,
            )
        )
        return CaseRerankResult(
            model=self._config.model.value,
            hits=ranked[: request.limit],
        )

    def _load_model(self) -> CrossEncoder:
        if self._model is None:
            # 조립만으로 모델을 내려받지 않고 실제 Case 검색이 발생할 때 지연 로드한다.
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
