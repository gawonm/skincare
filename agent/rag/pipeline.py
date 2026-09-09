"""검색 결과와 적용 조건 평가를 하나의 RAG 진입점으로 조립한다."""

from agent.rag.ports import EvidenceRetriever
from agent.rag.schemas import (
    ApplicabilityAssessment,
    ApplicabilityRequest,
    ApplicabilityStatus,
    EvidenceBundle,
    EvidenceConditions,
    EvidenceSearchRequest,
)


class EvidenceApplicabilityEvaluator:
    """미상 조건을 안전 확정으로 바꾸지 않는 최소 적용성 평가기."""

    def assess(self, request: ApplicabilityRequest) -> ApplicabilityAssessment:
        evidence_conditions = request.evidence.conditions
        known_conditions = request.known_conditions
        missing_fields = self._find_missing_fields(evidence_conditions, known_conditions)
        if missing_fields:
            return ApplicabilityAssessment(
                evidence_id=request.evidence.evidence_id,
                status=ApplicabilityStatus.LIMITED,
                reasons=[f"적용 조건 미상: {field}" for field in missing_fields],
            )
        return ApplicabilityAssessment(
            evidence_id=request.evidence.evidence_id,
            status=ApplicabilityStatus.APPLICABLE,
            reasons=["fixture에 기재된 조건 범위에서만 적용 가능"],
        )

    def _find_missing_fields(
        self,
        evidence: EvidenceConditions,
        known: EvidenceConditions,
    ) -> list[str]:
        fields = (
            "concentration",
            "formulation",
            "route",
            "usage",
            "duration",
        )
        return [
            field
            for field in fields
            if getattr(evidence, field) is not None and getattr(known, field) is None
        ]


class EvidencePipeline:
    """백엔드가 검색 세부 단계를 알지 않도록 RAG 호출을 캡슐화한다."""

    def __init__(
        self,
        retriever: EvidenceRetriever,
        evaluator: EvidenceApplicabilityEvaluator,
    ) -> None:
        self._retriever = retriever
        self._evaluator = evaluator

    async def run(self, request: EvidenceSearchRequest) -> EvidenceBundle:
        result = await self._retriever.search(request)
        assessments = [
            self._evaluator.assess(ApplicabilityRequest(evidence=record))
            for record in result.records
        ]
        return EvidenceBundle(search=result, assessments=assessments)
