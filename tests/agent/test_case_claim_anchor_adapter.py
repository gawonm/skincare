from agent.rag.case_claim_anchor_adapter import CaseClaimToEvidenceQueryAnchorAdapter
from agent.rag.case_claim_schemas import (
    CaseClaimIngredientResolutionStatus,
    CaseClaimType,
    ExtractedCaseClaim,
    ExtractedIngredientMention,
    ResolvedCaseClaim,
    ResolvedCaseClaimIngredient,
)
from agent.rag.schemas import (
    EvidenceClaimTopic,
    EvidenceQueryOrigin,
    IngredientMatchMode,
    IngredientScope,
)


class CaseClaimAnchorFixture:
    def claim(self, *, combination: bool = False, fully_resolved: bool = True) -> ResolvedCaseClaim:
        names = ["나이아신아마이드", "징크피씨에이"] if combination else ["나이아신아마이드"]
        extracted = ExtractedCaseClaim(
            case_id="CASE-1",
            claim_type=(
                CaseClaimType.COMBINATION_EFFECT
                if combination
                else CaseClaimType.INGREDIENT_EFFECT
            ),
            ingredients=[ExtractedIngredientMention(raw_name=name) for name in names],
            source_quote="와 ".join(names) + "는 피지 조절에 도움을 줍니다.",
        )
        resolutions = [
            ResolvedCaseClaimIngredient(
                raw_name=name,
                ingredient_id=(
                    f"ingredient:{index}"
                    if fully_resolved or index == 1
                    else None
                ),
                status=(
                    CaseClaimIngredientResolutionStatus.MATCHED
                    if fully_resolved or index == 1
                    else CaseClaimIngredientResolutionStatus.UNRESOLVED
                ),
            )
            for index, name in enumerate(names, start=1)
        ]
        return ResolvedCaseClaim(
            statement_id="case-claim:1",
            claim=extracted,
            ingredients=resolutions,
        )


class TestCaseClaimToEvidenceQueryAnchorAdapter:
    def test_단일_Claim을_CASE_CLAIM_Evidence_anchor로_변환한다(self) -> None:
        fixture = CaseClaimAnchorFixture()

        anchor = CaseClaimToEvidenceQueryAnchorAdapter().adapt(
            fixture.claim(),
            request_id="request-1",
            evidence_query="피지 관련 효능 및 주의사항",
        )

        assert anchor is not None
        assert anchor.origin is EvidenceQueryOrigin.CASE_CLAIM
        assert anchor.origin_ref == "case-claim:1"
        assert anchor.ingredient_scope is IngredientScope.SINGLE
        assert anchor.ingredient_refs == ["ingredient:1"]
        assert anchor.claim_topic is EvidenceClaimTopic.EFFICACY
        assert anchor.query_text == "나이아신아마이드: 피지 관련 효능 및 주의사항"

    def test_완전히_매칭된_조합은_ALL_anchor로_변환한다(self) -> None:
        fixture = CaseClaimAnchorFixture()

        anchor = CaseClaimToEvidenceQueryAnchorAdapter().adapt(
            fixture.claim(combination=True),
            request_id="request-1",
            evidence_query="피지 관련 효능 및 주의사항",
        )

        assert anchor is not None
        assert anchor.ingredient_scope is IngredientScope.MULTI
        assert anchor.ingredient_match_mode is IngredientMatchMode.ALL
        assert anchor.claim_topic is EvidenceClaimTopic.COMBINATION

    def test_일부만_매칭된_조합은_anchor를_만들지_않는다(self) -> None:
        fixture = CaseClaimAnchorFixture()

        anchor = CaseClaimToEvidenceQueryAnchorAdapter().adapt(
            fixture.claim(combination=True, fully_resolved=False),
            request_id="request-1",
            evidence_query="피지 관련 효능 및 주의사항",
        )

        assert anchor is None
