"""Claim 검색 결과를 Evidence 검색 anchor로 결정적으로 변환한다."""

from typing import ClassVar
from uuid import NAMESPACE_URL, uuid5

from agent.rag.claim_schemas import (
    ClaimHit,
    ClaimIngredientMatchingStatus,
    ClaimStatementType,
)
from agent.rag.schemas import (
    EvidenceClaimTopic,
    EvidenceQueryAnchor,
    EvidenceQueryOrigin,
    IngredientMatchMode,
    IngredientScope,
)


class ClaimHitToEvidenceQueryAnchorAdapter:
    """계약에서 허용한 Claim과 확정 성분만 Evidence 검색 대상으로 승격한다."""

    _TOPIC_MAP: ClassVar[dict[ClaimStatementType, EvidenceClaimTopic]] = {
        ClaimStatementType.INGREDIENT_EFFECT_CLAIM: EvidenceClaimTopic.EFFICACY,
        ClaimStatementType.USAGE_INSTRUCTION: EvidenceClaimTopic.USAGE_INSTRUCTION,
        ClaimStatementType.COMBINATION_CLAIM: EvidenceClaimTopic.COMBINATION,
    }

    def adapt(self, hit: ClaimHit, *, request_id: str) -> EvidenceQueryAnchor | None:
        topic = self._TOPIC_MAP.get(hit.statement_type)
        if topic is None:
            return None
        matched_refs = [
            ref
            for ref in hit.ingredient_refs
            if ref.matching_status is ClaimIngredientMatchingStatus.MATCHED
            and ref.ingredient_id is not None
        ]
        ingredient_ids = list(
            dict.fromkeys(ref.ingredient_id for ref in matched_refs if ref.ingredient_id is not None)
        )
        if not ingredient_ids:
            return None
        if hit.statement_type is ClaimStatementType.COMBINATION_CLAIM and len(ingredient_ids) < 2:
            # 조합 Claim 일부만 매칭됐을 때 단일 성분 효능으로 축소 검증하면 원래 주장이 바뀐다.
            return None
        scope = IngredientScope.SINGLE if len(ingredient_ids) == 1 else IngredientScope.MULTI
        return EvidenceQueryAnchor(
            anchor_id=str(uuid5(NAMESPACE_URL, f"claim-anchor:{request_id}:{hit.statement_id}")),
            request_id=request_id,
            origin=EvidenceQueryOrigin.CLAIM_HIT,
            origin_ref=hit.statement_id,
            ingredient_scope=scope,
            ingredient_refs=ingredient_ids,
            ingredient_match_mode=(
                IngredientMatchMode.ALL if scope is IngredientScope.MULTI else None
            ),
            claim_topic=topic,
            query_text=hit.verification_query(),
            query_terms=list(
                dict.fromkeys(
                    ref.raw_name for ref in matched_refs if ref.raw_name is not None
                )
            ),
        )
