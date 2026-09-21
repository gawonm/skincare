"""BGE 교차 인코더로 NIA Case 후보를 Top-3까지 재정렬한다."""

from typing import cast

from agent.rag.case_schemas import CaseRerankRequest, CaseRerankResult
from agent.rag.ports import CaseReranker
from agent.rag.retrieval.cross_encoder import (
    CrossEncoderScoringRequest,
    LocalBgeCrossEncoderScorer,
    RerankerTextPair,
)
from agent.rag.schemas import LocalRerankerConfig


class LocalBgeCaseRerankerV2M3(CaseReranker):
    """질문과 Case 원문을 함께 읽는 로컬 교차 인코더 재정렬기."""

    def __init__(
        self,
        config: LocalRerankerConfig,
        scorer: LocalBgeCrossEncoderScorer | None = None,
    ) -> None:
        self._config = config
        self._scorer = scorer or LocalBgeCrossEncoderScorer(config)

    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        scoring = await self._scorer.score(
            CrossEncoderScoringRequest(
                pairs=[
                    RerankerTextPair(
                        query=request.query,
                        document=candidate.page_content,
                    )
                    for candidate in request.candidates
                ]
            )
        )
        ranked = [
            candidate.model_copy(update={"rerank_score": float(score)})
            for candidate, score in zip(request.candidates, scoring.scores, strict=True)
        ]
        ranked.sort(
            key=lambda candidate: (
                -cast(float, candidate.rerank_score),
                -candidate.vector_similarity,
                candidate.case_id,
            )
        )
        return CaseRerankResult(
            model=scoring.model,
            hits=ranked[: request.limit],
        )
