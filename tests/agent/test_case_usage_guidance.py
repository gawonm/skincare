"""NIA Case 사용법이 관련 성분과 연결된 경우에만 루틴 입력이 되는지 검증한다."""

from agent.rag.case_claim_schemas import (
    CaseClaimIngredientResolutionStatus,
    CaseClaimType,
    ExtractedCaseClaim,
    ExtractedIngredientMention,
    ResolvedCaseClaim,
    ResolvedCaseClaimIngredient,
)
from agent.rag.case_schemas import (
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseSearchHit,
)
from agent.rag.case_usage_guidance import CaseUsageGuidanceExtractor


class CaseUsageGuidanceFixture:
    def case(self) -> CaseSearchHit:
        return CaseSearchHit(
            case_id="CASE-1",
            page_content=(
                "[질문]\n피지가 많아요.\n\n"
                "[추론]\n"
                "2. 성분 선택 및 근거 제시\n"
                "살리실산은 피지 관리에 도움을 줍니다.\n"
                "3. 사용법 및 관리방안\n"
                "살리실산은 저녁에 소량부터 사용합니다.\n"
                "4. 추가 주의사항\n"
                "자극이 있으면 중단합니다."
            ),
            text_version="nia_case_text/v1",
            dataset_split=CaseDatasetSplit.TRAINING,
            metadata=CaseMetadata(
                target_concern="피지",
                gender="여성",
                age=25,
                skin_type="지성",
                skin_concerns=["피지"],
            ),
            provenance=CaseProvenance(
                archive_name="training.zip",
                member_name="records.jsonl",
                line_number=1,
            ),
            vector_similarity=0.9,
        )

    def resolved_claim(
        self,
        *,
        raw_name: str = "살리실산",
        matched: bool = True,
    ) -> ResolvedCaseClaim:
        return ResolvedCaseClaim(
            statement_id=f"case-claim:{raw_name}",
            claim=ExtractedCaseClaim(
                case_id="CASE-1",
                claim_type=CaseClaimType.INGREDIENT_EFFECT,
                ingredients=[ExtractedIngredientMention(raw_name=raw_name)],
                source_quote=f"{raw_name}은 피지 관리에 도움을 줍니다.",
            ),
            ingredients=[
                ResolvedCaseClaimIngredient(
                    raw_name=raw_name,
                    ingredient_id="ingredient:salicylic" if matched else None,
                    canonical_name="살리실릭애씨드" if matched else None,
                    status=(
                        CaseClaimIngredientResolutionStatus.MATCHED
                        if matched
                        else CaseClaimIngredientResolutionStatus.UNRESOLVED
                    ),
                )
            ],
        )


class TestCaseUsageGuidanceExtractor:
    def test_사용법_구간과_매칭된_성분만_연결한다(self) -> None:
        fixture = CaseUsageGuidanceFixture()

        result = CaseUsageGuidanceExtractor().extract(
            [fixture.case()],
            [fixture.resolved_claim()],
        )

        assert len(result) == 1
        assert result[0].source_id == "nia-case-usage:CASE-1"
        assert result[0].ingredient_ids == ["ingredient:salicylic"]
        assert result[0].text == (
            "3. 사용법 및 관리방안\n살리실산은 저녁에 소량부터 사용합니다."
        )
        assert "4. 추가 주의사항" not in result[0].text

    def test_미확정이거나_사용법에_없는_성분은_제외한다(self) -> None:
        fixture = CaseUsageGuidanceFixture()

        result = CaseUsageGuidanceExtractor().extract(
            [fixture.case()],
            [
                fixture.resolved_claim(matched=False),
                fixture.resolved_claim(raw_name="나이아신아마이드"),
            ],
        )

        assert result == []
