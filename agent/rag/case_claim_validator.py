"""LLM이 추출한 Case Claim을 원문 기준으로 결정적으로 검증한다."""

from agent.rag.case_claim_schemas import (
    CaseClaimValidationReason,
    CaseClaimValidationRequest,
    CaseClaimValidationResult,
    ExtractedCaseClaim,
    RejectedCaseClaim,
)


class CaseClaimValidator:
    """Case ID·exact quote·성분명·중복을 검사하고 실패 이유를 보존한다."""

    def validate(self, request: CaseClaimValidationRequest) -> CaseClaimValidationResult:
        cases = {case.case_id: case for case in request.cases}
        valid_claims: list[ExtractedCaseClaim] = []
        rejected_claims: list[RejectedCaseClaim] = []
        seen_keys: set[tuple[str, str, tuple[str, ...], str]] = set()

        for claim in request.claims:
            case = cases.get(claim.case_id)
            if case is None:
                rejected_claims.append(
                    self._reject(
                        claim,
                        CaseClaimValidationReason.UNKNOWN_CASE_ID,
                        "Claim의 case_id가 rerank Top-3에 없습니다.",
                    )
                )
                continue
            if claim.source_quote not in case.page_content:
                rejected_claims.append(
                    self._reject(
                        claim,
                        CaseClaimValidationReason.QUOTE_NOT_FOUND,
                        "source_quote가 해당 Case 원문의 정확한 부분 문자열이 아닙니다.",
                    )
                )
                continue
            quote = claim.source_quote.casefold()
            missing_names = [
                ingredient.raw_name
                for ingredient in claim.ingredients
                if ingredient.raw_name.casefold() not in quote
            ]
            if missing_names:
                rejected_claims.append(
                    self._reject(
                        claim,
                        CaseClaimValidationReason.INGREDIENT_NOT_IN_QUOTE,
                        "source_quote에 없는 성분명이 있습니다: " + ", ".join(missing_names),
                    )
                )
                continue

            key = self._deduplication_key(claim)
            if key in seen_keys:
                rejected_claims.append(
                    self._reject(
                        claim,
                        CaseClaimValidationReason.DUPLICATE_CLAIM,
                        "동일한 Case Claim이 이미 채택되었습니다.",
                    )
                )
                continue
            seen_keys.add(key)
            valid_claims.append(claim)

        return CaseClaimValidationResult(
            valid_claims=valid_claims,
            rejected_claims=rejected_claims,
        )

    def _deduplication_key(
        self,
        claim: ExtractedCaseClaim,
    ) -> tuple[str, str, tuple[str, ...], str]:
        ingredient_names = tuple(
            sorted(ingredient.raw_name.casefold() for ingredient in claim.ingredients)
        )
        return (
            claim.case_id,
            claim.claim_type.value,
            ingredient_names,
            claim.source_quote,
        )

    def _reject(
        self,
        claim: ExtractedCaseClaim,
        reason: CaseClaimValidationReason,
        message: str,
    ) -> RejectedCaseClaim:
        return RejectedCaseClaim(claim=claim, reason=reason, message=message)
