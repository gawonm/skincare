"""Claim별 Evidence 판정과 추천 성분 등급 선정을 결정적 규칙으로 수행한다."""

from agent.rag.claim_schemas import (
    ClaimVerificationBundle,
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationStatus,
    EvidenceSupportLevel,
    IngredientRecommendationCandidate,
    IngredientRecommendationSet,
    RecommendationBasis,
)
from agent.rag.pipeline import EvidencePipeline
from agent.rag.schemas import (
    ApplicabilityStatus,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    IngredientVerificationResult,
    LookupStatus,
    PerTargetResult,
    UnverifiableReason,
)

CLAIM_ONLY_LIMITATION = "현재 연결된 근거로 이 Claim을 충분히 확인하지 못했습니다."


class ClaimEvidenceVerifier:
    """검색 성공과 검증 가능한 생성 결과를 구분해 Claim 상태를 확정한다."""

    def __init__(self, pipeline: EvidencePipeline) -> None:
        self._pipeline = pipeline

    async def verify(self, request: ClaimVerificationRequest) -> ClaimVerificationResult:
        anchor = request.anchor
        bundle = await self._pipeline.run(
            EvidenceSearchRequest(
                query=anchor.query_text,
                target_ids=anchor.ingredient_refs,
                combination_target_ids=(
                    anchor.ingredient_refs if len(anchor.ingredient_refs) > 1 else []
                ),
                known_conditions=request.known_conditions,
            )
        )
        if bundle.search.status is LookupStatus.ERROR:
            return self._without_evidence(
                request,
                ClaimVerificationStatus.ERROR,
                bundle.search.error_message or "Evidence 검색 도구가 원인을 제공하지 않았습니다.",
            )
        if bundle.search.status is LookupStatus.UNSUPPORTED:
            return self._without_evidence(
                request,
                ClaimVerificationStatus.UNSUPPORTED,
                bundle.search.error_message or "현재 Evidence 검색기가 이 요청을 지원하지 않습니다.",
            )
        if bundle.search.status is LookupStatus.NO_RESULTS:
            return self._without_evidence(
                request,
                ClaimVerificationStatus.INSUFFICIENT,
                "현재 연결된 Evidence에서 관련 근거를 찾지 못했습니다.",
            )
        return self._from_success(request, bundle)

    def _from_success(
        self,
        request: ClaimVerificationRequest,
        bundle: EvidenceBundle,
    ) -> ClaimVerificationResult:
        generated = bundle.generated
        if generated is None:
            return self._without_evidence(
                request,
                ClaimVerificationStatus.INSUFFICIENT,
                "검색 자료는 있으나 검증 가능한 근거 문장이 생성되지 않았습니다.",
            )

        target_ids = set(request.anchor.ingredient_refs)
        results = {
            item.target_id: item.result
            for item in generated.per_target
            if item.target_id in target_ids
        }
        verified_results: list[IngredientVerificationResult] = []
        records: dict[str, EvidenceRecord] = {}
        if (
            len(target_ids) > 1
            and generated.combination is not None
            and generated.combination.has_verifiable_evidence
        ):
            verified_results.append(generated.combination)
            records = self._validated_result_records(
                bundle,
                generated.combination,
                request.anchor.ingredient_refs,
            )
        elif len(target_ids) == 1 and all(
            ingredient_id in results and results[ingredient_id].has_verifiable_evidence
            for ingredient_id in target_ids
        ):
            # 단독 근거를 합쳐 조합 효능·안전성까지 입증한 것으로 확대하지 않도록 단일 대상에만 허용한다.
            for ingredient_id in request.anchor.ingredient_refs:
                result = results[ingredient_id]
                verified_results.append(result)
                current = self._validated_result_records(bundle, result, [ingredient_id])
                if not current:
                    records = {}
                    break
                records.update(current)

        summaries = list(
            dict.fromkeys(result.answer for result in verified_results if result.answer)
        )
        if verified_results and records and summaries:
            return ClaimVerificationResult(
                statement_id=self._statement_id(request),
                ingredient_ids=request.anchor.ingredient_refs,
                status=ClaimVerificationStatus.SUPPORTED,
                evidence_ids=list(records),
                evidence_records=list(records.values()),
                evidence_support_level=self._support_level(bundle, records),
                summary=" ".join(summaries),
            )

        reasons = self._unverifiable_reasons(request, generated.per_target)
        if len(target_ids) > 1:
            if generated.combination is None:
                reasons.append(UnverifiableReason.MISSING_COMBINATION_EVIDENCE.value)
            elif generated.combination.unverifiable_reason is not None:
                reasons.append(generated.combination.unverifiable_reason.value)
            elif generated.combination.has_verifiable_evidence and not records:
                reasons.append(UnverifiableReason.CITATION_VALIDATION_FAILED.value)
        return ClaimVerificationResult(
            statement_id=self._statement_id(request),
            ingredient_ids=request.anchor.ingredient_refs,
            status=ClaimVerificationStatus.INSUFFICIENT,
            reasons=list(dict.fromkeys(reasons))
            or [UnverifiableReason.NO_EVIDENCE_FOUND.value],
        )

    def _validated_result_records(
        self,
        bundle: EvidenceBundle,
        result: IngredientVerificationResult,
        expected_target_ids: list[str],
    ) -> dict[str, EvidenceRecord]:
        searched = {record.evidence_id: record for record in bundle.search.records}
        records: dict[str, EvidenceRecord] = {}
        expected = set(expected_target_ids)
        for claim in result.claims:
            for source in claim.sources:
                if searched.get(source.evidence_id) != source:
                    return {}
                if not expected.issubset(source.target_ids):
                    return {}
                records[source.evidence_id] = source
        return records

    def _support_level(
        self,
        bundle: EvidenceBundle,
        records: dict[str, EvidenceRecord],
    ) -> EvidenceSupportLevel:
        if any(
            record.review_status is not EvidenceReviewStatus.VERIFIED
            for record in records.values()
        ):
            return EvidenceSupportLevel.UNREVIEWED
        assessments = {item.evidence_id: item.status for item in bundle.assessments}
        if any(
            assessments.get(evidence_id) is not ApplicabilityStatus.APPLICABLE
            for evidence_id in records
        ):
            # 적용성 평가가 누락된 근거도 검수 완료만으로 현재 질문에 맞다고 승격하지 않는다.
            return EvidenceSupportLevel.LIMITED
        return EvidenceSupportLevel.VERIFIED

    def _unverifiable_reasons(
        self,
        request: ClaimVerificationRequest,
        per_target: list[PerTargetResult],
    ) -> list[str]:
        target_ids = set(request.anchor.ingredient_refs)
        return [
            item.result.unverifiable_reason.value
            for item in per_target
            if item.target_id in target_ids and item.result.unverifiable_reason is not None
        ]

    def _without_evidence(
        self,
        request: ClaimVerificationRequest,
        status: ClaimVerificationStatus,
        reason: str,
    ) -> ClaimVerificationResult:
        return ClaimVerificationResult(
            statement_id=self._statement_id(request),
            ingredient_ids=request.anchor.ingredient_refs,
            status=status,
            reasons=[reason],
        )

    def _statement_id(self, request: ClaimVerificationRequest) -> str:
        statement_id = request.anchor.origin_ref
        if statement_id is None:
            raise ValueError("Claim 검증용 Evidence anchor에는 origin_ref가 필요합니다.")
        return statement_id


class IngredientRecommendationSelector:
    """Evidence 상태를 상품 포함 정책으로 변환하되 오류와 상반 근거는 보류한다."""

    _BLOCKING_STATUSES = frozenset(
        (
            ClaimVerificationStatus.CONTRADICTED,
            ClaimVerificationStatus.UNSUPPORTED,
            ClaimVerificationStatus.ERROR,
        )
    )

    def select(self, bundle: ClaimVerificationBundle) -> IngredientRecommendationSet:
        blocked = {
            ingredient_id
            for result in bundle.results
            if result.status in self._BLOCKING_STATUSES
            for ingredient_id in result.ingredient_ids
        }
        ingredient_order = list(
            dict.fromkeys(
                ingredient_id
                for result in bundle.results
                for ingredient_id in result.ingredient_ids
                if ingredient_id not in blocked
            )
        )
        candidates = [
            self._candidate(ingredient_id, bundle)
            for ingredient_id in ingredient_order
        ]
        verified = [
            candidate
            for candidate in candidates
            if candidate is not None
            and candidate.basis is RecommendationBasis.VERIFIED_EVIDENCE
        ]
        limited = [
            candidate
            for candidate in candidates
            if candidate is not None
            and candidate.basis is RecommendationBasis.LIMITED_EVIDENCE
        ]
        unreviewed = [
            candidate
            for candidate in candidates
            if candidate is not None
            and candidate.basis is RecommendationBasis.UNREVIEWED_EVIDENCE
        ]
        claim_only = [
            candidate
            for candidate in candidates
            if candidate is not None and candidate.basis is RecommendationBasis.CLAIM_ONLY
        ]
        return IngredientRecommendationSet(
            candidates=[*verified, *limited, *unreviewed, *claim_only]
        )

    def _candidate(
        self,
        ingredient_id: str,
        bundle: ClaimVerificationBundle,
    ) -> IngredientRecommendationCandidate | None:
        related = [
            result for result in bundle.results if ingredient_id in result.ingredient_ids
        ]
        supported = [
            result
            for result in related
            if result.status is ClaimVerificationStatus.SUPPORTED
        ]
        insufficient = [
            result
            for result in related
            if result.status is ClaimVerificationStatus.INSUFFICIENT
        ]
        selected = supported or insufficient
        if not selected:
            return None
        levels = {
            result.evidence_support_level
            for result in supported
            if result.evidence_support_level is not None
        }
        if EvidenceSupportLevel.VERIFIED in levels:
            basis = RecommendationBasis.VERIFIED_EVIDENCE
        elif EvidenceSupportLevel.LIMITED in levels:
            basis = RecommendationBasis.LIMITED_EVIDENCE
        elif EvidenceSupportLevel.UNREVIEWED in levels:
            basis = RecommendationBasis.UNREVIEWED_EVIDENCE
        else:
            basis = RecommendationBasis.CLAIM_ONLY
        return IngredientRecommendationCandidate(
            ingredient_id=ingredient_id,
            basis=basis,
            statement_ids=list(dict.fromkeys(result.statement_id for result in related)),
            evidence_ids=list(
                dict.fromkeys(
                    evidence_id for result in supported for evidence_id in result.evidence_ids
                )
            ),
            limitation=CLAIM_ONLY_LIMITATION if basis is RecommendationBasis.CLAIM_ONLY else None,
        )
