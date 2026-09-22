"""BGE 교차 인코더로 NIA Case 후보를 Top-3까지 재정렬한다."""

from typing import ClassVar, cast

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

    _DOCUMENT_TEMPLATE: ClassVar[str] = (
        "[사례 문맥]\n"
        "연령: {age}세\n"
        "성별: {gender}\n"
        "피부 타입: {skin_type}\n"
        "피부 고민: {skin_concerns}\n\n"
        "[질문·답변·추론]\n"
        "{page_content}"
    )

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
                        # 연령·성별은 원문 임베딩에 없으므로 최종 교차 인코더가 저장
                        # 메타데이터와 사용자 문맥을 함께 비교할 수 있게만 덧붙인다.
                        document=self._DOCUMENT_TEMPLATE.format(
                            age=candidate.metadata.age,
                            gender=candidate.metadata.gender,
                            skin_type=candidate.metadata.skin_type,
                            skin_concerns=", ".join(candidate.metadata.skin_concerns),
                            page_content=candidate.page_content,
                        ),
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
