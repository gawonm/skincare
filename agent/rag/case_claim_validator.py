"""LLM이 추출한 Case Claim을 원문 기준으로 결정적으로 검증한다."""

from typing import ClassVar

from agent.rag.case_claim_schemas import (
    CaseClaimType,
    CaseClaimValidationReason,
    CaseClaimValidationRequest,
    CaseClaimValidationResult,
    ExtractedCaseClaim,
    RejectedCaseClaim,
)


class CaseClaimValidator:
    """Case ID·exact quote·성분명·중복을 검사하고 실패 이유를 보존한다."""

    _COMBINATION_MARKERS: ClassVar[tuple[str, ...]] = (
        "함께",
        "같이",
        "병용",
        "조합",
        "동시에",
        "혼합",
        "시너지",
    )

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
            if self._is_ingredient_name_only(claim):
                rejected_claims.append(
                    self._reject(
                        claim,
                        CaseClaimValidationReason.INGREDIENT_NAME_ONLY_QUOTE,
                        "성분명만 있는 인용문은 효능 Claim으로 사용할 수 없습니다.",
                    )
                )
                continue

            combination_error = self._combination_error(claim)
            if combination_error is not None:
                reason, message = combination_error
                rejected_claims.append(self._reject(claim, reason, message))
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

    def _is_ingredient_name_only(self, claim: ExtractedCaseClaim) -> bool:
        if claim.claim_type is not CaseClaimType.INGREDIENT_EFFECT:
            return False
        quote = self._normalized_text(claim.source_quote)
        ingredient = self._normalized_text(claim.ingredients[0].raw_name)
        return quote == ingredient

    def _normalized_text(self, value: str) -> str:
        return "".join(character.casefold() for character in value if character.isalnum())

    def _combination_error(
        self,
        claim: ExtractedCaseClaim,
    ) -> tuple[CaseClaimValidationReason, str] | None:
        relation_quote = claim.combination_relation_quote
        if claim.claim_type is CaseClaimType.INGREDIENT_EFFECT:
            if relation_quote is None:
                return None
            return (
                CaseClaimValidationReason.COMBINATION_RELATION_NOT_EXPLICIT,
                "개별 성분 Claim에는 조합 관계 인용문을 넣을 수 없습니다.",
            )
        if relation_quote is None or relation_quote not in claim.source_quote:
            return (
                CaseClaimValidationReason.COMBINATION_RELATION_NOT_FOUND,
                "조합 Claim의 관계 인용문이 source_quote에 정확히 존재하지 않습니다.",
            )
        normalized = relation_quote.casefold()
        if not any(marker in normalized for marker in self._COMBINATION_MARKERS):
            return (
                CaseClaimValidationReason.COMBINATION_RELATION_NOT_EXPLICIT,
                "조합 Claim에 함께 사용하거나 공동 작용한다는 명시적 관계 표현이 없습니다.",
            )
        return None

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
