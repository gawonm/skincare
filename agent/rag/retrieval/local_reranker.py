"""BGE 교차 인코더로 1차 검색 후보를 로컬 재정렬한다."""

from typing import cast

from agent.rag.ports import EvidenceReranker
from agent.rag.retrieval.cross_encoder import (
    CrossEncoderScoringRequest,
    LocalBgeCrossEncoderScorer,
    RerankerTextPair,
)
from agent.rag.schemas import LocalRerankerConfig, RerankRequest, RerankResult


class LocalBgeRerankerV2M3(EvidenceReranker):
    """질문과 각 청크를 함께 읽는 교차 인코더 기반 재정렬기."""

    def __init__(
        self,
        config: LocalRerankerConfig,
        scorer: LocalBgeCrossEncoderScorer | None = None,
    ) -> None:
        self._config = config
        self._scorer = scorer or LocalBgeCrossEncoderScorer(config)

    async def rerank(self, request: RerankRequest) -> RerankResult:
        scoring = await self._scorer.score(
            CrossEncoderScoringRequest(
                pairs=[
                    RerankerTextPair(
                        query=request.query,
                        document=candidate.chunk.content,
                    )
                    for candidate in request.candidates
                ]
            )
        )
        ranked = [
            candidate.model_copy(update={"reranker_score": float(score)})
            for candidate, score in zip(request.candidates, scoring.scores, strict=True)
        ]
        ranked.sort(
            key=lambda candidate: (
                -cast(float, candidate.reranker_score),
                -candidate.fused_score,
                candidate.chunk.chunk_id,
            )
        )
        return RerankResult(
            model=scoring.model,
            chunks=ranked[: request.limit],
        )
