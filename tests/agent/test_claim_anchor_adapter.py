"""ClaimHit에서 EvidenceQueryAnchor로의 결정적 계약 변환을 검증한다."""

from agent.rag.claim_anchor_adapter import ClaimHitToEvidenceQueryAnchorAdapter
from agent.rag.claim_schemas import (
    ClaimHit,
    ClaimIngestionDecision,
    ClaimIngredientMatchingStatus,
    ClaimIngredientRef,
    ClaimStatementType,
    ClaimSupportStatus,
)
from agent.rag.schemas import EvidenceClaimTopic, IngredientMatchMode, IngredientScope


class ClaimAnchorFixture:
    ANNOTATION_VERSION = "fixture-claim-v1"
    REQUEST_ID = "request-1"

    def ingredient(
        self,
        raw_name: str | None,
        ingredient_id: str | None,
        status: ClaimIngredientMatchingStatus,
    ) -> ClaimIngredientRef:
        return ClaimIngredientRef(
            raw_name=raw_name,
            ingredient_id=ingredient_id,
            matching_status=status,
        )

    def hit(
        self,
        statement_type: ClaimStatementType,
        ingredients: list[ClaimIngredientRef],
    ) -> ClaimHit:
        return ClaimHit(
            claim_chunk_id=f"chunk:{statement_type.value}",
            statement_id=f"statement:{statement_type.value}",
            statement_type=statement_type,
            content=f"{statement_type.value} 검증 문장",
            score=0.9,
            ingredient_refs=ingredients,
            source_record_id="record-1",
            annotation_version=self.ANNOTATION_VERSION,
            decision=ClaimIngestionDecision.INGESTIBLE_STRUCTURED,
            support_status=ClaimSupportStatus.UNVERIFIED,
        )


class TestClaimHitToEvidenceQueryAnchorAdapter:
    def test_ingredient_effect_claim_maps_to_single_efficacy_anchor(self) -> None:
        fixture = ClaimAnchorFixture()
        hit = fixture.hit(
            ClaimStatementType.INGREDIENT_EFFECT_CLAIM,
            [
                fixture.ingredient(
                    "NIACINAMIDE",
                    "ingredient:niacinamide",
                    ClaimIngredientMatchingStatus.MATCHED,
                )
            ],
        )

        anchor = ClaimHitToEvidenceQueryAnchorAdapter().adapt(
            hit,
            request_id=fixture.REQUEST_ID,
        )

        assert anchor is not None
        assert anchor.claim_topic is EvidenceClaimTopic.EFFICACY
        assert anchor.ingredient_scope is IngredientScope.SINGLE
        assert anchor.ingredient_refs == ["ingredient:niacinamide"]

    def test_usage_instruction_maps_to_usage_topic(self) -> None:
        fixture = ClaimAnchorFixture()
        hit = fixture.hit(
            ClaimStatementType.USAGE_INSTRUCTION,
            [
                fixture.ingredient(
                    "RETINOL",
                    "ingredient:retinol",
                    ClaimIngredientMatchingStatus.MATCHED,
                )
            ],
        )

        anchor = ClaimHitToEvidenceQueryAnchorAdapter().adapt(
            hit,
            request_id=fixture.REQUEST_ID,
        )

        assert anchor is not None
        assert anchor.claim_topic is EvidenceClaimTopic.USAGE_INSTRUCTION

    def test_matched_ingredient_without_raw_name_uses_claim_content(self) -> None:
        fixture = ClaimAnchorFixture()
        hit = fixture.hit(
            ClaimStatementType.INGREDIENT_EFFECT_CLAIM,
            [
                fixture.ingredient(
                    None,
                    "ingredient:niacinamide",
                    ClaimIngredientMatchingStatus.MATCHED,
                )
            ],
        )

        anchor = ClaimHitToEvidenceQueryAnchorAdapter().adapt(
            hit,
            request_id=fixture.REQUEST_ID,
        )

        assert anchor is not None
        assert anchor.query_text == hit.content
        assert anchor.query_terms == []

    def test_combination_claim_requires_all_matched_ingredients(self) -> None:
        fixture = ClaimAnchorFixture()
        hit = fixture.hit(
            ClaimStatementType.COMBINATION_CLAIM,
            [
                fixture.ingredient(
                    "NIACINAMIDE",
                    "ingredient:niacinamide",
                    ClaimIngredientMatchingStatus.MATCHED,
                ),
                fixture.ingredient(
                    "RETINOL",
                    "ingredient:retinol",
                    ClaimIngredientMatchingStatus.MATCHED,
                ),
            ],
        )

        anchor = ClaimHitToEvidenceQueryAnchorAdapter().adapt(
            hit,
            request_id=fixture.REQUEST_ID,
        )

        assert anchor is not None
        assert anchor.claim_topic is EvidenceClaimTopic.COMBINATION
        assert anchor.ingredient_scope is IngredientScope.MULTI
        assert anchor.ingredient_match_mode is IngredientMatchMode.ALL

    def test_unresolved_ingredient_is_not_promoted(self) -> None:
        fixture = ClaimAnchorFixture()
        hit = fixture.hit(
            ClaimStatementType.INGREDIENT_EFFECT_CLAIM,
            [
                fixture.ingredient(
                    "UNKNOWN EXTRACT",
                    None,
                    ClaimIngredientMatchingStatus.UNRESOLVED,
                )
            ],
        )

        anchor = ClaimHitToEvidenceQueryAnchorAdapter().adapt(
            hit,
            request_id=fixture.REQUEST_ID,
        )

        assert anchor is None

    def test_partially_matched_combination_is_not_reduced_to_single_ingredient(self) -> None:
        fixture = ClaimAnchorFixture()
        hit = fixture.hit(
            ClaimStatementType.COMBINATION_CLAIM,
            [
                fixture.ingredient(
                    "NIACINAMIDE",
                    "ingredient:niacinamide",
                    ClaimIngredientMatchingStatus.MATCHED,
                ),
                fixture.ingredient(
                    "UNKNOWN EXTRACT",
                    None,
                    ClaimIngredientMatchingStatus.UNRESOLVED,
                ),
            ],
        )

        anchor = ClaimHitToEvidenceQueryAnchorAdapter().adapt(
            hit,
            request_id=fixture.REQUEST_ID,
        )

        assert anchor is None
