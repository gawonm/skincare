from uuid import uuid4

from agent.rag.retrieval.hybrid_retriever import HybridRetriever
from models.rag_chunk import RagChunk, RagChunkField, RagConfidenceTier, RagSourceTable


def _chunk(content: str = "내용") -> RagChunk:
    chunk = RagChunk(
        ingredient_id=None,
        source_table=RagSourceTable.NIA_QA,
        chunk_field=RagChunkField.NIA_ANSWER,
        chunk_index=0,
        content=content,
        embedding_model="test",
        confidence_tier=RagConfidenceTier.AI_GENERATED_REVIEWED,
        cites_cir=False,
        source_title="테스트",
        source_url=None,
        citation_refs=[],
    )
    chunk.id = uuid4()
    return chunk


def test_fuse_prioritizes_chunk_found_in_both_searches() -> None:
    shared = _chunk("양쪽에서 찾은 청크")
    only_vector = _chunk("벡터 검색만")
    only_bm25 = _chunk("BM25 검색만")

    result = HybridRetriever().fuse(
        vector_results=[(shared, 0.9), (only_vector, 0.5)],
        bm25_results=[(shared, 3.0), (only_bm25, 1.0)],
        top_k=10,
    )

    assert result[0].chunk_id == shared.id
    assert result[0].vector_rank == 1
    assert result[0].bm25_rank == 1
    assert result[0].vector_similarity == 0.9
    assert result[0].bm25_relevance == 3.0


def test_fuse_respects_top_k() -> None:
    chunks = [(_chunk(f"청크{i}"), 1.0 - i * 0.1) for i in range(5)]
    result = HybridRetriever().fuse(vector_results=chunks, bm25_results=[], top_k=2)
    assert len(result) == 2


def test_fuse_deduplicates_chunk_appearing_in_both_lists() -> None:
    chunk = _chunk()
    result = HybridRetriever().fuse(
        vector_results=[(chunk, 0.8)], bm25_results=[(chunk, 2.0)], top_k=10
    )
    assert len(result) == 1


def test_fuse_orders_ties_deterministically_regardless_of_which_search_found_them() -> None:
    """RRF 총점이 완전히 같은 두 청크(한쪽은 벡터 1등, 다른 쪽은 BM25 1등)의 순서가
    어느 검색 결과 리스트에 넣었는지와 무관하게 항상 같아야 한다(chunk id로 동점 해소)."""
    a = _chunk("A")
    b = _chunk("B")

    # A는 벡터 1등, B는 BM25 1등 - 둘 다 RRF 점수 1/61로 동점.
    first = HybridRetriever().fuse(vector_results=[(a, 0.9)], bm25_results=[(b, 3.0)], top_k=10)
    # 어느 채널에서 찾았는지만 바꿔도(A<->B) 동점 관계는 그대로다.
    second = HybridRetriever().fuse(vector_results=[(b, 0.9)], bm25_results=[(a, 3.0)], top_k=10)

    assert first[0].fused_score == first[1].fused_score

    # 동점 해소 기준은 chunk id 문자열 비교뿐이다 - 어느 채널(벡터/BM25)에서 찾았는지와
    # 무관하게, id가 더 작은 쪽이 항상 먼저 나와야 한다.
    expected_winner = a.id if str(a.id) < str(b.id) else b.id
    assert first[0].chunk_id == expected_winner
    assert second[0].chunk_id == expected_winner
