from agent.rag.case_schemas import (
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseSearchHit,
    CaseSearchResult,
)
from agent.rag.retrieval.case_result_fusion import (
    CaseSearchContribution,
    CaseSearchFusionRequest,
    CaseSearchResultFusion,
)
from agent.rag.schemas import LookupStatus


class TestCaseSearchResultFusion:
    def test_여러_질의에_반복된_Case를_RRF로_우선한다(self) -> None:
        first = CaseSearchContribution(
            query="프로필 질의",
            result=self._success(
                self._hit("case-a", 0.91),
                self._hit("case-b", 0.72),
            ),
        )
        second = CaseSearchContribution(
            query="고민 질의",
            result=self._success(
                self._hit("case-b", 0.95),
                self._hit("case-c", 0.83),
            ),
        )

        result = CaseSearchResultFusion().fuse(
            CaseSearchFusionRequest(contributions=[first, second])
        )

        assert result.search_result.status is LookupStatus.SUCCESS
        assert [hit.case_id for hit in result.search_result.hits] == [
            "case-b",
            "case-a",
            "case-c",
        ]
        assert result.candidates[0].hit.vector_similarity == 0.95
        assert result.candidates[0].matched_queries == ["프로필 질의", "고민 질의"]

    def test_RRF_동점은_최대_벡터_유사도와_Case_ID로_결정한다(self) -> None:
        result = CaseSearchResultFusion().fuse(
            CaseSearchFusionRequest(
                contributions=[
                    CaseSearchContribution(
                        query="질의 A",
                        result=self._success(self._hit("case-b", 0.8)),
                    ),
                    CaseSearchContribution(
                        query="질의 B",
                        result=self._success(self._hit("case-c", 0.5)),
                    ),
                    CaseSearchContribution(
                        query="질의 C",
                        result=self._success(self._hit("case-a", 0.5)),
                    ),
                ]
            )
        )

        assert [hit.case_id for hit in result.search_result.hits] == [
            "case-b",
            "case-a",
            "case-c",
        ]

    def test_일부_검색_실패는_성공_결과를_유지하고_실패를_노출한다(self) -> None:
        result = CaseSearchResultFusion().fuse(
            CaseSearchFusionRequest(
                contributions=[
                    CaseSearchContribution(
                        query="성공 질의",
                        result=self._success(self._hit("case-a", 0.8)),
                    ),
                    CaseSearchContribution(
                        query="실패 질의",
                        result=CaseSearchResult(
                            status=LookupStatus.ERROR,
                            error_message="DB 검색 실패",
                        ),
                    ),
                ]
            )
        )

        assert result.search_result.status is LookupStatus.SUCCESS
        assert [hit.case_id for hit in result.search_result.hits] == ["case-a"]
        assert len(result.failures) == 1
        assert result.failures[0].query == "실패 질의"
        assert result.failures[0].message == "DB 검색 실패"

    def test_모든_검색이_무결과면_NO_RESULTS를_반환한다(self) -> None:
        result = CaseSearchResultFusion().fuse(
            CaseSearchFusionRequest(
                contributions=[
                    CaseSearchContribution(
                        query="무결과 질의",
                        result=CaseSearchResult(status=LookupStatus.NO_RESULTS),
                    )
                ]
            )
        )

        assert result.search_result.status is LookupStatus.NO_RESULTS
        assert result.candidates == []
        assert result.failures == []

    def test_모든_검색이_실패하면_원인을_포함한_ERROR를_반환한다(self) -> None:
        result = CaseSearchResultFusion().fuse(
            CaseSearchFusionRequest(
                contributions=[
                    CaseSearchContribution(
                        query="실패 질의",
                        result=CaseSearchResult(
                            status=LookupStatus.ERROR,
                            error_message="연결 실패",
                        ),
                    )
                ]
            )
        )

        assert result.search_result.status is LookupStatus.ERROR
        assert result.search_result.error_message is not None
        assert "실패 질의" in result.search_result.error_message
        assert "연결 실패" in result.search_result.error_message

    def _success(self, *hits: CaseSearchHit) -> CaseSearchResult:
        return CaseSearchResult(status=LookupStatus.SUCCESS, hits=list(hits))

    def _hit(self, case_id: str, similarity: float) -> CaseSearchHit:
        return CaseSearchHit(
            case_id=case_id,
            page_content=f"{case_id} 본문",
            text_version="nia_case_text/v1",
            dataset_split=CaseDatasetSplit.TRAINING,
            metadata=CaseMetadata(
                target_concern="건조",
                gender="여성",
                age=30,
                skin_type="건성",
                skin_concerns=["건조"],
            ),
            provenance=CaseProvenance(
                archive_name="training.zip",
                member_name=f"{case_id}.jsonl",
                line_number=1,
            ),
            vector_similarity=similarity,
        )
