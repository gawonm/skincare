"""표준 성분이 확정된 Case Claim을 Evidence 검색 anchor로 변환한다."""

from uuid import NAMESPACE_URL, uuid5

from agent.rag.case_claim_schemas import CaseClaimType, ResolvedCaseClaim
from agent.rag.schemas import (
    EvidenceClaimTopic,
    EvidenceQueryAnchor,
    EvidenceQueryOrigin,
    IngredientMatchMode,
    IngredientScope,
)


class CaseClaimToEvidenceQueryAnchorAdapter:
    """부분 매칭 조합 Claim이 단일 성분 근거로 축소되지 않게 변환 경계를 지킨다."""

    def adapt(
        self,
        claim: ResolvedCaseClaim,
        *,
        request_id: str,
        evidence_query: str,
    ) -> EvidenceQueryAnchor | None:
        if not claim.is_fully_resolved():
            return None
        ingredient_ids = list(dict.fromkeys(claim.matched_ingredient_ids()))
        if (
            claim.claim.claim_type is CaseClaimType.COMBINATION_EFFECT
            and len(ingredient_ids) < 2
        ):
            return None
        scope = IngredientScope.SINGLE if len(ingredient_ids) == 1 else IngredientScope.MULTI
        names = [
            ingredient.canonical_name or ingredient.raw_name
            for ingredient in claim.ingredients
        ]
        return EvidenceQueryAnchor(
            anchor_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"case-claim-anchor:{request_id}:{claim.statement_id}",
                )
            ),
            request_id=request_id,
            origin=EvidenceQueryOrigin.CASE_CLAIM,
            origin_ref=claim.statement_id,
            ingredient_scope=scope,
            ingredient_refs=ingredient_ids,
            ingredient_match_mode=(
                IngredientMatchMode.ALL if scope is IngredientScope.MULTI else None
            ),
            claim_topic=(
                EvidenceClaimTopic.COMBINATION
                if claim.claim.claim_type is CaseClaimType.COMBINATION_EFFECT
                else EvidenceClaimTopic.EFFICACY
            ),
            # Case의 효능 문장이나 상품·루틴 지시를 재사용하면 Evidence 검색을 지배할 수 있으므로
            # 표준 성분명과 질의 계획에서 정제한 효능·주의 축만 사용한다.
            query_text=f"{' + '.join(names)}: {evidence_query}",
            query_terms=names,
        )
