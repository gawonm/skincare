"""Claim 탐색 결과와 Evidence 검증 결과를 혼동하지 않고 응답 상태에 반영한다."""

from agent.citations import EvidenceCitationMapper
from agent.rag.case_claim_schemas import CaseClaimIngredientResolutionStatus
from agent.rag.claim_schemas import ClaimVerificationResult, ClaimVerificationStatus
from agent.rag.schemas import (
    ApplicabilityStatus,
    EvidenceBundle,
    EvidenceRecord,
    LookupStatus,
    UnverifiableReason,
)
from agent.runtime import AgentRuntime
from agent.schemas import (
    AgentState,
    ChatStatus,
    EvidenceAnswer,
    RagRoute,
    UnresolvedItem,
    UnresolvedKind,
)

NO_CLAIM_MESSAGE = "현재 고민과 연결되는 탐색용 성분 주장을 찾지 못했습니다."
NO_EVIDENCE_MESSAGE = "현재 연결된 검색 자료에서 관련 공인 근거를 찾지 못했습니다."


class RagResponseAssembler:
    """Claim은 탐색 표현으로, Evidence는 검증 표현과 Citation으로 조립한다."""

    def __init__(self, runtime: AgentRuntime, citations: EvidenceCitationMapper) -> None:
        self._runtime = runtime
        self._citations = citations

    def append(self, state: AgentState) -> None:
        self._append_claim_context(state)
        if state.rag_route is RagRoute.CLAIM_THEN_EVIDENCE:
            self._append_claim_verification(state)
            return
        bundle = state.evidence_bundle
        if bundle is None:
            self._append_missing_evidence_path(state)
            return
        if bundle.search.status is LookupStatus.ERROR:
            detail = (
                "근거 검색 도구가 실패해 Claim을 검증하지 못했습니다."
                if state.rag_route is RagRoute.CLAIM_THEN_EVIDENCE
                else "공인 근거 검색 도구가 실패했습니다."
            )
            state.response_parts.append(detail)
            return
        if bundle.search.status is LookupStatus.NO_RESULTS:
            self._append_no_evidence(state)
            return
        if bundle.search.status is LookupStatus.UNSUPPORTED:
            state.status = ChatStatus.PARTIAL
            detail = bundle.search.error_message or "현재 검색기가 이 근거 요청을 지원하지 않습니다."
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.UNSUPPORTED_CONDITION, detail=detail)
            )
            state.response_parts.append(detail)
            return
        if bundle.generated is not None:
            self._append_generated(state, bundle)
            self._append_question_limitations(state)
            return
        self._append_records(state, bundle)
        self._append_question_limitations(state)

    def _append_claim_verification(self, state: AgentState) -> None:
        verification = state.claim_verification_bundle
        if verification is None or not verification.results:
            self._append_missing_evidence_path(state)
            self._append_unresolved_claim_anchors(state)
            return
        for result in verification.results:
            self._append_claim_verification_result(state, result)
        self._append_unresolved_claim_anchors(state)

    def _append_unresolved_claim_anchors(self, state: AgentState) -> None:
        case_claim = state.case_claim_bundle
        if case_claim is not None:
            names = list(
                dict.fromkeys(
                    ingredient.raw_name
                    for claim in case_claim.resolved_claims
                    for ingredient in claim.ingredients
                    if ingredient.status is not CaseClaimIngredientResolutionStatus.MATCHED
                )
            )
            if names:
                state.status = ChatStatus.PARTIAL
                detail = "표준 성분을 확정하지 못한 Case Claim 성분: " + ", ".join(names)
                state.unresolved.append(
                    UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=detail)
                )
                state.response_parts.append(detail)
            return
        claim = state.claim_bundle
        if claim is not None and claim.unresolved_anchors:
            state.status = ChatStatus.PARTIAL
            names = list(dict.fromkeys(anchor.raw_name for anchor in claim.unresolved_anchors))
            detail = "표준 성분을 확정하지 못한 Claim 성분: " + ", ".join(names)
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=detail)
            )
            state.response_parts.append(detail)

    def _append_claim_verification_result(
        self,
        state: AgentState,
        result: ClaimVerificationResult,
    ) -> None:
        if result.status is ClaimVerificationStatus.SUPPORTED:
            self._store_evidence(state, result.evidence_records)
            summary = result.summary or "검증 가능한 공인 근거가 확인됐습니다."
            state.artifacts.append(
                EvidenceAnswer(
                    answer_id=self._runtime.stable_id(
                        state, f"claim-evidence-answer:{result.statement_id}"
                    ),
                    subject=result.statement_id,
                    summary=summary,
                    evidence_ids=result.evidence_ids,
                    is_demo=any(record.is_demo for record in result.evidence_records),
                )
            )
            state.response_parts.append("공인 근거 확인: " + summary)
            return
        if result.status is ClaimVerificationStatus.INSUFFICIENT:
            state.status = ChatStatus.PARTIAL
            detail = (
                f"Claim {result.statement_id}: 현재 연결된 공인 근거로 충분히 확인하지 못했습니다."
            )
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.NO_EVIDENCE, detail=detail)
            )
            state.response_parts.append(detail)
            return
        if result.status is ClaimVerificationStatus.UNSUPPORTED:
            state.status = ChatStatus.PARTIAL
            detail = "; ".join(result.reasons) or "현재 검색기가 이 Claim 검증을 지원하지 않습니다."
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.UNSUPPORTED_CONDITION, detail=detail)
            )
            state.response_parts.append(detail)
            return
        if result.status is ClaimVerificationStatus.CONTRADICTED:
            state.status = ChatStatus.PARTIAL
            detail = "; ".join(result.reasons) or "Claim과 명시적으로 상반되는 근거가 확인됐습니다."
            state.unresolved.append(UnresolvedItem(kind=UnresolvedKind.CONFLICT, detail=detail))
            state.response_parts.append(detail)
            return
        detail = "; ".join(result.reasons) or "Evidence 검색 도구 오류로 Claim 검증을 보류했습니다."
        state.response_parts.append(detail)

    def _append_claim_context(self, state: AgentState) -> None:
        case_claim = state.case_claim_bundle
        if (
            case_claim is not None
            and case_claim.validation is not None
            and case_claim.validation.valid_claims
        ):
            descriptions = list(
                dict.fromkeys(
                    claim.source_quote for claim in case_claim.validation.valid_claims
                )
            )
            state.response_parts.append(
                "유사한 사용자 사례의 탐색적 주장: " + " / ".join(descriptions)
            )
            if state.case_bundle is not None and state.case_bundle.rerank_fallback_used:
                state.response_parts.append(
                    "Case 재정렬 실패로 1차 벡터 검색 순위 Top-3를 사용했습니다."
                )
            return
        bundle = state.claim_bundle
        if bundle is None or bundle.search.status is not LookupStatus.SUCCESS:
            return
        descriptions = list(
            dict.fromkeys(
                hit.display_text()
                for hit in bundle.search.hits
            )
        )
        if not descriptions:
            return
        state.response_parts.append(
            "유사한 사용자 사례의 탐색적 주장: " + " / ".join(descriptions)
        )

    def _append_missing_evidence_path(self, state: AgentState) -> None:
        case_bundle = state.case_bundle
        case_claim = state.case_claim_bundle
        if state.rag_route is RagRoute.CLAIM_THEN_EVIDENCE and case_bundle is not None:
            if case_bundle.search.status is LookupStatus.ERROR:
                state.response_parts.append(
                    "NIA Case 검색 실패로 Claim 탐색 경로를 시작하지 못했습니다."
                )
                return
            if case_bundle.search.status is LookupStatus.NO_RESULTS:
                state.status = ChatStatus.PARTIAL
                state.unresolved.append(
                    UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=NO_CLAIM_MESSAGE)
                )
                state.response_parts.append(NO_CLAIM_MESSAGE)
                return
            if case_claim is not None and case_claim.extraction.status is LookupStatus.ERROR:
                state.response_parts.append("NIA Case Claim 추출 오류로 성분 검증을 진행하지 못했습니다.")
                return
            if (
                case_claim is None
                or case_claim.extraction.status is LookupStatus.NO_RESULTS
                or case_claim.validation is None
                or not case_claim.validation.valid_claims
            ):
                state.status = ChatStatus.PARTIAL
                state.unresolved.append(
                    UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=NO_CLAIM_MESSAGE)
                )
                state.response_parts.append(NO_CLAIM_MESSAGE)
                return
        claim = state.claim_bundle
        if state.rag_route is RagRoute.EVIDENCE_ONLY:
            if not state.response_parts:
                state.response_parts.append("공인 근거 검색을 진행하지 못했습니다.")
            return
        if claim is not None and claim.search.status is LookupStatus.ERROR:
            state.response_parts.append("Claim 검색 실패로 공인 근거 검증 경로를 시작하지 못했습니다.")
            return
        if claim is not None and claim.search.status is LookupStatus.NO_RESULTS:
            state.status = ChatStatus.PARTIAL
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=NO_CLAIM_MESSAGE)
            )
            state.response_parts.append(NO_CLAIM_MESSAGE)
            return
        state.status = ChatStatus.PARTIAL
        detail = "Claim에서 공인 근거를 검색할 표준 성분을 확정하지 못했습니다."
        state.unresolved.append(
            UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=detail)
        )
        state.response_parts.append(detail)

    def _append_no_evidence(self, state: AgentState) -> None:
        state.status = ChatStatus.PARTIAL
        state.unresolved.append(
            UnresolvedItem(kind=UnresolvedKind.NO_EVIDENCE, detail=NO_EVIDENCE_MESSAGE)
        )
        state.response_parts.append(NO_EVIDENCE_MESSAGE)

    def _append_records(self, state: AgentState, bundle: EvidenceBundle) -> None:
        excluded_ids = {
            item.evidence_id
            for item in bundle.assessments
            if item.status is ApplicabilityStatus.NOT_APPLICABLE
        }
        records = [
            record for record in bundle.search.records if record.evidence_id not in excluded_ids
        ]
        if not records:
            state.status = ChatStatus.PARTIAL
            state.response_parts.append("검색된 근거를 현재 조건에 적용할 수 없습니다.")
            state.unresolved.extend(
                UnresolvedItem(kind=UnresolvedKind.UNSUPPORTED_CONDITION, detail=reason)
                for item in bundle.assessments
                for reason in item.reasons
            )
            return
        self._store_evidence(state, records)
        summary = "\n".join(f"[{record.source_title}] {record.text}" for record in records)
        answer = EvidenceAnswer(
            answer_id=self._runtime.stable_id(state, "evidence-answer"),
            subject=self._runtime.require_parsed(state).query,
            summary=summary,
            evidence_ids=[record.evidence_id for record in records],
            assessments=bundle.assessments,
            is_demo=any(record.is_demo for record in records),
        )
        state.artifacts.append(answer)
        state.response_parts.append(answer.summary)
        self._append_limitations(state, bundle)

    def _append_generated(self, state: AgentState, bundle: EvidenceBundle) -> None:
        generated = bundle.generated
        if generated is None:
            raise ValueError("생성된 Evidence 결과가 없습니다.")
        results = [
            (f"대상 {index}", item.result)
            for index, item in enumerate(generated.per_target, start=1)
        ]
        if generated.combination is not None:
            results.append(("병용 근거", generated.combination))
        if generated.free_text is not None:
            results.append(("질문에 대한 근거", generated.free_text))
        messages: list[str] = []
        records: dict[str, EvidenceRecord] = {}
        for label, result in results:
            if result.has_verifiable_evidence:
                messages.append(f"{label}: {result.answer}")
                for answered in result.claims:
                    for record in answered.sources:
                        records[record.evidence_id] = record
                continue
            reason = result.unverifiable_reason or UnverifiableReason.NO_EVIDENCE_FOUND
            detail = self._unverifiable_message(reason)
            messages.append(f"{label}: {detail}")
            state.status = ChatStatus.PARTIAL
            state.unresolved.append(
                UnresolvedItem(kind=UnresolvedKind.NO_EVIDENCE, detail=detail)
            )
        for item in bundle.assessments:
            if item.evidence_id in records and item.status is not ApplicabilityStatus.APPLICABLE:
                messages.append("적용 한계: " + "; ".join(item.reasons))
        summary = "\n".join(messages) or NO_EVIDENCE_MESSAGE
        self._store_evidence(state, list(records.values()))
        state.artifacts.append(
            EvidenceAnswer(
                answer_id=self._runtime.stable_id(state, "evidence-answer"),
                subject=self._runtime.require_parsed(state).query,
                summary=summary,
                evidence_ids=list(records),
                assessments=bundle.assessments,
                is_demo=any(record.is_demo for record in records.values()),
                generated=generated,
            )
        )
        state.response_parts.append(summary)

    def _store_evidence(self, state: AgentState, records: list[EvidenceRecord]) -> None:
        known_ids = {record.evidence_id for record in state.evidence}
        new_records = [record for record in records if record.evidence_id not in known_ids]
        state.evidence.extend(new_records)
        known_citations = {citation.evidence_id for citation in state.citations}
        state.citations.extend(
            self._citations.map(record)
            for record in new_records
            if record.evidence_id not in known_citations
        )

    def _append_limitations(self, state: AgentState, bundle: EvidenceBundle) -> None:
        limitations = list(
            dict.fromkeys(
                reason
                for item in bundle.assessments
                for reason in item.reasons
                if item.status is not ApplicabilityStatus.APPLICABLE
            )
        )
        if limitations:
            state.response_parts.append("적용 한계: " + "; ".join(limitations))

    def _append_question_limitations(self, state: AgentState) -> None:
        query = self._runtime.require_parsed(state).query
        if any(word in query for word in ("병용", "같이", "괜찮")):
            state.response_parts.append(
                "개별 성분 자료만으로 두 완제품의 병용 안전성을 확정할 수 없습니다."
            )
        if "농도" in query or "ph" in query.casefold():
            state.unresolved.append(
                UnresolvedItem(
                    kind=UnresolvedKind.MISSING_INFORMATION,
                    detail="제품별 공개 농도 또는 pH가 없으면 적용 범위를 확정할 수 없습니다.",
                )
            )

    def _unverifiable_message(self, reason: UnverifiableReason) -> str:
        messages = {
            UnverifiableReason.NO_EVIDENCE_FOUND: "확인할 근거를 찾지 못했습니다.",
            UnverifiableReason.UNREVIEWED_EVIDENCE: "검수된 근거가 없어 답변을 보류합니다.",
            UnverifiableReason.NOT_RELEVANT_TO_QUESTION: "질문 항목을 뒷받침할 근거가 부족합니다.",
            UnverifiableReason.MISSING_COMBINATION_EVIDENCE: "대상을 함께 다루는 병용 근거가 없습니다.",
            UnverifiableReason.CITATION_VALIDATION_FAILED: "출처·조건 검증을 통과한 답변이 없습니다.",
        }
        return messages[reason]
