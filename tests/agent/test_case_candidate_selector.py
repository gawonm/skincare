from agent.rag.case_schemas import (
    DEFAULT_CASE_RERANK_CANDIDATE_LIMIT,
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseSearchHit,
)
from agent.rag.retrieval.case_candidate_selector import (
    CaseCandidateSelectionRequest,
    CaseMetadataCandidateSelector,
    NiaCaseConcernCategory,
    NiaCaseSkinType,
)


class CaseCandidateSelectorFixture:
    def hit(
        self,
        case_id: str,
        target_concern: str,
        *,
        gender: str = "여성",
        skin_type: str = "중성",
        skin_concerns: list[str] | None = None,
        rank: int = 1,
    ) -> CaseSearchHit:
        return CaseSearchHit(
            case_id=case_id,
            page_content=f"[질문]\n{case_id} 질문",
            text_version="nia_case_text/v1",
            dataset_split=CaseDatasetSplit.TRAINING,
            metadata=CaseMetadata(
                target_concern=target_concern,
                gender=gender,
                age=30,
                skin_type=skin_type,
                skin_concerns=skin_concerns or [target_concern],
            ),
            provenance=CaseProvenance(
                archive_name="training.zip",
                member_name="records.jsonl",
                line_number=rank,
            ),
            vector_similarity=1.0 - rank / 100.0,
        )


class TestCaseMetadataCandidateSelector:
    def test_희소_고민은_직접_일치_후_피부타입_일치와_상위_벡터_순위로_보충한다(self) -> None:
        fixture = CaseCandidateSelectorFixture()
        candidates = [
            fixture.hit("DRY-1", NiaCaseConcernCategory.HYPERKERATOSIS_DRYNESS, skin_type="건성", rank=1),
            fixture.hit("ACNE-OILY", NiaCaseConcernCategory.ACNE, skin_type="지성", rank=2),
            fixture.hit(
                "SENSITIVE-MALE",
                NiaCaseConcernCategory.SENSITIVITY,
                gender="남성",
                skin_type="건성",
                rank=3,
            ),
            fixture.hit("PORE-DRY-FEMALE", NiaCaseConcernCategory.PORES, skin_type="건성", rank=4),
            fixture.hit("DRY-2", NiaCaseConcernCategory.HYPERKERATOSIS_DRYNESS, skin_type="복합성", rank=5),
        ]

        result = CaseMetadataCandidateSelector().select(
            CaseCandidateSelectionRequest(
                query="30살 여성 겨울철 건조하고 민감한 피부",
                skin_concerns=["건조", "민감"],
                candidates=candidates,
            )
        )

        assert result.detected_categories == [
            NiaCaseConcernCategory.HYPERKERATOSIS_DRYNESS,
            NiaCaseConcernCategory.SENSITIVITY,
        ]
        assert result.detected_skin_types == [NiaCaseSkinType.DRY]
        assert [hit.case_id for hit in result.candidates] == [
            "DRY-1",
            "SENSITIVE-MALE",
            "DRY-2",
            "PORE-DRY-FEMALE",
            "ACNE-OILY",
        ]
        assert result.direct_match_count == 3

    def test_직접_일치가_충분해도_나머지_Dense_후보를_보존한다(self) -> None:
        fixture = CaseCandidateSelectorFixture()
        candidates = [
            *[
                fixture.hit(f"PORE-{idx}", NiaCaseConcernCategory.PORES, rank=idx)
                for idx in range(1, 12)
            ],
            fixture.hit("ACNE-1", NiaCaseConcernCategory.ACNE, rank=12),
        ]

        result = CaseMetadataCandidateSelector().select(
            CaseCandidateSelectionRequest(
                query="모공이 넓어 보여서 고민",
                candidates=candidates,
            )
        )

        assert [hit.case_id for hit in result.candidates] == [
            *[f"PORE-{idx}" for idx in range(1, 12)],
            "ACNE-1",
        ]
        assert result.direct_match_count == 11

    def test_직접_일치가_부족하면_벡터_순위로_보충한다(self) -> None:
        fixture = CaseCandidateSelectorFixture()
        candidates = [
            fixture.hit("ACNE-1", NiaCaseConcernCategory.ACNE, rank=1),
            fixture.hit("PORE-1", NiaCaseConcernCategory.PORES, rank=2),
            fixture.hit("WRINKLE-1", NiaCaseConcernCategory.WRINKLES, rank=3),
        ]

        result = CaseMetadataCandidateSelector().select(
            CaseCandidateSelectionRequest(
                query="모공이 넓어 보여서 고민",
                candidates=candidates,
            )
        )

        assert [hit.case_id for hit in result.candidates] == [
            "PORE-1",
            "ACNE-1",
            "WRINKLE-1",
        ]
        assert result.direct_match_count == 1

    def test_고민_범주를_찾지_못하면_벡터_상위_40건까지_유지한다(self) -> None:
        fixture = CaseCandidateSelectorFixture()
        candidates = [
            fixture.hit(
                f"CASE-{rank}",
                NiaCaseConcernCategory.ACNE,
                rank=rank,
            )
            for rank in range(1, 46)
        ]

        result = CaseMetadataCandidateSelector().select(
            CaseCandidateSelectionRequest(
                query="피부 상태와 비슷한 사례",
                candidates=candidates,
            )
        )

        assert len(result.candidates) == DEFAULT_CASE_RERANK_CANDIDATE_LIMIT
        assert [hit.case_id for hit in result.candidates] == [
            f"CASE-{rank}"
            for rank in range(1, DEFAULT_CASE_RERANK_CANDIDATE_LIMIT + 1)
        ]
        assert result.direct_match_count == 0
