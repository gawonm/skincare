"""검색 결과의 관련도와 사용자 조건에 대한 적용성을 분리한다."""

from agent.rag.ports import EvidenceRetriever
from agent.rag.schemas import (
    ApplicabilityAssessment,
    ApplicabilityRequest,
    ApplicabilityStatus,
    EvidenceBundle,
    EvidenceConditions,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    LookupStatus,
)

CONDITION_FIELDS = tuple(EvidenceConditions.model_fields)
NORMALIZED_ROUTES = frozenset(("topical", "oral", "intravenous"))


class EvidenceApplicabilityEvaluator:
    """명확한 조건 불일치만 배제하고 미검수·자유문 조건은 검토 대상으로 남긴다."""

    def assess(self, request: ApplicabilityRequest) -> ApplicabilityAssessment:
        record = request.evidence
        known = request.known_conditions
        reasons: list[str] = []
        status = ApplicabilityStatus.APPLICABLE
        for field in CONDITION_FIELDS:
            required = getattr(record.conditions, field)
            if field == "jurisdiction":
                required = record.jurisdiction or required
            actual = getattr(known, field)
            if required is None:
                continue
            if actual is None:
                reasons.append(f"적용 조건 미상: {field}")
            elif required.strip().casefold() != actual.strip().casefold():
                # 농도 범위·동의어·제형의 의미 비교를 문자열 불일치로 확정하지 않는다.
                reasons.append(f"적용 조건 일치 확인 필요: {field} ({required} / {actual})")
                if field == "route" and {required, actual}.issubset(NORMALIZED_ROUTES):
                    status = ApplicabilityStatus.NOT_APPLICABLE
            if reasons and status is not ApplicabilityStatus.NOT_APPLICABLE:
                status = ApplicabilityStatus.LIMITED
        if record.raw_conditions:
            reasons.append(f"원문 조건의 별도 검토 필요: {record.raw_conditions}")
            if status is ApplicabilityStatus.APPLICABLE:
                status = ApplicabilityStatus.LIMITED
        if record.review_status is not EvidenceReviewStatus.VERIFIED or record.is_demo:
            reasons.append("미검수 자료 또는 개발 fixture이므로 실제 적용을 확정할 수 없음")
            if status is ApplicabilityStatus.APPLICABLE:
                status = ApplicabilityStatus.UNKNOWN
        if record.document_version is None:
            reasons.append("출처 버전 미상: 최신성 검토 필요")
            if status is ApplicabilityStatus.APPLICABLE:
                status = ApplicabilityStatus.LIMITED
        return ApplicabilityAssessment(
            evidence_id=record.evidence_id,
            status=status,
            reasons=reasons
            or ["검수된 해당 근거의 명시 조건과 일치; 제품 병용 안전성 확정은 아님"],
        )


class EvidencePipeline:
    """조회 계약을 통해 얻은 자료를 평가하며 DB나 수집 파이프라인을 소유하지 않는다."""

    def __init__(
        self, retriever: EvidenceRetriever, evaluator: EvidenceApplicabilityEvaluator
    ) -> None:
        self._retriever = retriever
        self._evaluator = evaluator

    async def run(self, request: EvidenceSearchRequest) -> EvidenceBundle:
        result = await self._retriever.search(request)
        assessments = (
            [
                self._evaluator.assess(
                    ApplicabilityRequest(
                        evidence=record,
                        known_conditions=request.known_conditions,
                    )
                )
                for record in result.records
            ]
            if result.status is LookupStatus.SUCCESS
            else []
        )
        return EvidenceBundle(search=result, assessments=assessments)
