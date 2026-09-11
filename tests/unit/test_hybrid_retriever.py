from agent.rag.retrieval.hybrid_retriever import HybridRetriever
from agent.rag.schemas import (
    EvidenceRecord,
    EvidenceReviewStatus,
    HybridFusionRequest,
    HybridSearchResult,
    LookupStatus,
    RagChunkDraft,
    RagRetrievalPolicy,
    RetrievedChunk,
)


class TestHybridRetriever:
    def _retriever(self) -> HybridRetriever:
        return HybridRetriever(RagRetrievalPolicy(free_text_min_vector_similarity=0.0, rrf_k=60))

    def _chunk(self, chunk_id: str, content: str = "내용") -> RagChunkDraft:
        return RagChunkDraft(
            chunk_id=chunk_id,
            field_id="test_field",
            content=content,
            evidence=EvidenceRecord(
                evidence_id=f"evidence-{chunk_id}",
                source_id="source-1",
                source_title="테스트",
                text=content,
                locator=f"test:{chunk_id}",
                review_status=EvidenceReviewStatus.VERIFIED,
                is_demo=False,
            ),
        )

    def _fuse(
        self,
        vector_results: list[RetrievedChunk],
        bm25_results: list[RetrievedChunk],
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        return self._retriever().fuse(
            HybridFusionRequest(
                results=HybridSearchResult(
                    status=LookupStatus.SUCCESS,
                    vector_results=vector_results,
                    bm25_results=bm25_results,
                ),
                limit=limit,
            )
        )

    def test_fuse_prioritizes_chunk_found_in_both_searches(self) -> None:
        shared = self._chunk("shared", "양쪽에서 찾은 청크")
        only_vector = self._chunk("vector", "벡터 검색만")
        only_bm25 = self._chunk("bm25", "BM25 검색만")

        result = self._fuse(
            [
                RetrievedChunk(chunk=shared, vector_similarity=0.9),
                RetrievedChunk(chunk=only_vector, vector_similarity=0.5),
            ],
            [
                RetrievedChunk(chunk=shared, bm25_relevance=3.0),
                RetrievedChunk(chunk=only_bm25, bm25_relevance=1.0),
            ],
        )

        assert result[0].chunk.chunk_id == shared.chunk_id
        assert result[0].vector_similarity == 0.9
        assert result[0].bm25_relevance == 3.0

    def test_fuse_respects_limit_and_deduplicates(self) -> None:
        chunks = [
            RetrievedChunk(chunk=self._chunk(f"chunk-{index}"), vector_similarity=1 - index * 0.1)
            for index in range(5)
        ]
        result = self._fuse(chunks, [chunks[0].model_copy(deep=True)], limit=2)

        assert len(result) == 2
        assert len({item.chunk.chunk_id for item in result}) == 2

    def test_fuse_orders_ties_by_chunk_id(self) -> None:
        first = self._chunk("a")
        second = self._chunk("b")
        result = self._fuse(
            [RetrievedChunk(chunk=second, vector_similarity=0.9)],
            [RetrievedChunk(chunk=first, bm25_relevance=3.0)],
        )

        assert result[0].fused_score == result[1].fused_score
        assert [item.chunk.chunk_id for item in result] == ["a", "b"]
