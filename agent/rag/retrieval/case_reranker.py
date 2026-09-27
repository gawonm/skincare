"""BGE 교차 인코더로 NIA Case 후보를 Top-3까지 재정렬한다."""

from typing import ClassVar, cast

from agent.rag.case_schemas import CaseRerankRequest, CaseRerankResult, CaseSearchHit
from agent.rag.ports import CaseReranker
from agent.rag.retrieval.case_care_compatibility import (
    CaseCareCompatibilityPolicy,
)
from agent.rag.retrieval.cross_encoder import (
    CrossEncoderScoringRequest,
    LocalBgeCrossEncoderScorer,
    RerankerTextPair,
)
from agent.rag.schemas import CareContext, LocalRerankerConfig


class LocalBgeCaseRerankerV2M3(CaseReranker):
    """질문과 Case 원문을 함께 읽는 로컬 교차 인코더 재정렬기."""

    _REASONING_LABEL: ClassVar[str] = "[추론]"
    _DOCUMENT_TEMPLATE: ClassVar[str] = (
        "[사례 문맥]\n"
        "대표 고민: {target_concern}\n"
        "피부 고민: {skin_concerns}\n"
        "피부 타입: {skin_type}\n"
        "연령: {age}세\n"
        "성별: {gender}\n\n"
        "[사례 질문·답변]\n"
        "{page_content}"
    )

    def __init__(
        self,
        config: LocalRerankerConfig,
        scorer: LocalBgeCrossEncoderScorer | None = None,
        care_compatibility: CaseCareCompatibilityPolicy | None = None,
    ) -> None:
        self._config = config
        self._scorer = scorer or LocalBgeCrossEncoderScorer(config)
        self._care_compatibility = care_compatibility or CaseCareCompatibilityPolicy()

    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        scoring = await self._scorer.score(
            CrossEncoderScoringRequest(
                pairs=[
                    RerankerTextPair(
                        query=request.query,
                        # 장문의 생성 추론이 질문·답변을 토큰 한도 밖으로 밀어내지 않도록
                        # 검색 관련성이 직접 드러나는 메타데이터와 원문 질문·답변만 전달한다.
                        document=self._DOCUMENT_TEMPLATE.format(
                            target_concern=candidate.metadata.target_concern,
                            skin_concerns=", ".join(candidate.metadata.skin_concerns),
                            skin_type=candidate.metadata.skin_type,
                            age=candidate.metadata.age,
                            gender=candidate.metadata.gender,
                            page_content=self._question_and_answer(candidate.page_content),
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
        safety_adjusted = self._remove_care_incompatible_candidates(
            request.care_context,
            ranked,
        )
        diversified = self._prioritize_unique_content(safety_adjusted)
        return CaseRerankResult(
            model=scoring.model,
            hits=diversified[: request.limit],
        )

    def _question_and_answer(self, page_content: str) -> str:
        # 임베딩 원문은 보존하고, 교차 인코더 입력에서만 생성 과정의 CoT를 제외한다.
        return page_content.split(self._REASONING_LABEL, maxsplit=1)[0].strip()

    def _prioritize_unique_content(
        self,
        ranked: list[CaseSearchHit],
    ) -> list[CaseSearchHit]:
        unique: list[CaseSearchHit] = []
        duplicates: list[CaseSearchHit] = []
        seen: set[str] = set()
        for candidate in ranked:
            content_key = " ".join(
                self._question_and_answer(candidate.page_content).casefold().split()
            )
            if content_key in seen:
                duplicates.append(candidate)
                continue
            seen.add(content_key)
            unique.append(candidate)
        # 서로 다른 사례가 부족할 때는 결과 수를 유지하기 위해 중복 후보로만 보충한다.
        return [*unique, *duplicates]

    def _remove_care_incompatible_candidates(
        self,
        care_context: CareContext,
        ranked: list[CaseSearchHit],
    ) -> list[CaseSearchHit]:
        compatible: list[CaseSearchHit] = []
        for candidate in ranked:
            assessment = self._care_compatibility.assess(
                care_context=care_context,
                page_content=candidate.page_content,
            )
            if assessment.is_incompatible():
                continue
            compatible.append(candidate)
        # 교차 인코더의 절대 점수 범위를 가정한 매직 감점값을 쓰지 않는다.
        # 안전 부적합 후보를 제외한 결과가 부족하면 위험 답변으로 Top-3를 채우지 않고
        # 더 적은 Case만 다음 Claim 단계에 전달한다.
        return compatible
