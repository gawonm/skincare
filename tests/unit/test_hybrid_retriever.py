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
        vector_results=[shared, only_vector], bm25_results=[shared, only_bm25], top_k=10
    )

    assert result[0].chunk_id == shared.id
    assert result[0].vector_rank == 1
    assert result[0].bm25_rank == 1


def test_fuse_respects_top_k() -> None:
    chunks = [_chunk(f"청크{i}") for i in range(5)]
    result = HybridRetriever().fuse(vector_results=chunks, bm25_results=[], top_k=2)
    assert len(result) == 2


def test_fuse_deduplicates_chunk_appearing_in_both_lists() -> None:
    chunk = _chunk()
    result = HybridRetriever().fuse(vector_results=[chunk], bm25_results=[chunk], top_k=10)
    assert len(result) == 1
