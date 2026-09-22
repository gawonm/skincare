"""NIA Case 검색과 런타임 Claim 추출 DTO의 경계 규칙을 검증한다."""

import pytest
from pydantic import ValidationError

from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimExtractionResult,
    CaseClaimType,
    ExtractedCaseClaim,
    ExtractedIngredientMention,
)
from agent.rag.case_schemas import (
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseRerankResult,
    CaseSearchHit,
    CaseSearchResult,
)
from agent.rag.schemas import LookupStatus


class TestCaseRuntimeClaimContract:
    def test_case_search_success_requires_hits(self) -> None:
        with pytest.raises(ValidationError, match="hit이 필요"):
            CaseSearchResult(status=LookupStatus.SUCCESS)

    def test_rerank_requires_scores(self) -> None:
        with pytest.raises(ValidationError, match="rerank_score"):
            CaseRerankResult(model="BAAI/bge-reranker-v2-m3", hits=[self._case_hit()])

    def test_extraction_request_rejects_duplicate_cases(self) -> None:
        case = self._case_hit()
        with pytest.raises(ValidationError, match="중복"):
            CaseClaimExtractionRequest(query="피지가 많아요", cases=[case, case])

    def test_individual_claim_requires_one_ingredient(self) -> None:
        with pytest.raises(ValidationError, match="정확히 1개"):
            ExtractedCaseClaim(
                case_id="CASE-1",
                claim_type=CaseClaimType.INGREDIENT_EFFECT,
                ingredients=[
                    ExtractedIngredientMention(raw_name="나이아신아마이드"),
                    ExtractedIngredientMention(raw_name="징크피씨에이"),
                ],
                source_quote="나이아신아마이드와 징크피씨에이가 언급되었습니다.",
            )

    def test_combination_claim_requires_two_ingredients(self) -> None:
        with pytest.raises(ValidationError, match="2개 이상"):
            ExtractedCaseClaim(
                case_id="CASE-1",
                claim_type=CaseClaimType.COMBINATION_EFFECT,
                ingredients=[ExtractedIngredientMention(raw_name="나이아신아마이드")],
                source_quote="나이아신아마이드가 언급되었습니다.",
            )

    def test_successful_extraction_requires_model(self) -> None:
        claim = ExtractedCaseClaim(
            case_id="CASE-1",
            claim_type=CaseClaimType.INGREDIENT_EFFECT,
            ingredients=[ExtractedIngredientMention(raw_name="나이아신아마이드")],
            source_quote="나이아신아마이드는 피지 조절에 도움을 줍니다.",
        )
        with pytest.raises(ValidationError, match="모델명"):
            CaseClaimExtractionResult(status=LookupStatus.SUCCESS, claims=[claim])

    def _case_hit(self) -> CaseSearchHit:
        return CaseSearchHit(
            case_id="CASE-1",
            page_content="나이아신아마이드는 피지 조절에 도움을 줍니다.",
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
                archive_name="TL_피지.zip",
                member_name="001/001.jsonl",
                line_number=1,
            ),
            vector_similarity=0.9,
        )
