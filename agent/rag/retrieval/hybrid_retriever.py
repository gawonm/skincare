"""벡터 검색과 BM25 검색 결과를 하나의 순위로 합친다(reciprocal rank fusion).

실제 벡터/BM25 쿼리는 `backend/repositories/rag_chunk_repository.py`(`RagChunkRepository`)가
실행한다 - SQLAlchemy 쿼리는 repositories에만 쓴다는 STRUCTURE.md 규칙 때문이다. 이 클래스는
이미 각각 랭킹까지 끝난 `list[RagChunk]` 두 개(순수 데이터)만 받아 병합 계산만 한다 -
세션도 리포지토리도 직접 만들지 않는다.
"""

from uuid import UUID

from agent.rag.schemas import RetrievedChunk
from models.rag_chunk import RagChunk

# RRF 공식 1/(k + rank)의 k. 순위 1위와 2위의 점수 차이를 완만하게 만들어, 한쪽 검색
# 방식에서만 極단적으로 높은 순위를 받은 결과가 결과를 독식하지 않게 한다. RRF 논문과
# 대부분의 하이브리드 검색 구현이 쓰는 관행값이다.
_RRF_K = 60


class HybridRetriever:
    """벡터 검색 순위와 BM25 검색 순위를 RRF로 합쳐 `RetrievedChunk` 목록을 만든다."""

    def fuse(
        self, vector_results: list[RagChunk], bm25_results: list[RagChunk], top_k: int
    ) -> list[RetrievedChunk]:
        vector_ranks = self._ranks_by_id(vector_results)
        bm25_ranks = self._ranks_by_id(bm25_results)
        chunks_by_id = {chunk.id: chunk for chunk in (*vector_results, *bm25_results)}

        scored: list[tuple[float, RagChunk, int | None, int | None]] = []
        for chunk_id, chunk in chunks_by_id.items():
            vector_rank = vector_ranks.get(chunk_id)
            bm25_rank = bm25_ranks.get(chunk_id)
            score = self._rrf_score(vector_rank) + self._rrf_score(bm25_rank)
            scored.append((score, chunk, vector_rank, bm25_rank))

        scored.sort(key=lambda item: item[0], reverse=True)

        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                content=chunk.content,
                chunk_field=chunk.chunk_field,
                confidence_tier=chunk.confidence_tier,
                source_title=chunk.source_title,
                source_url=chunk.source_url,
                citation_refs=tuple(chunk.citation_refs),
                vector_rank=vector_rank,
                bm25_rank=bm25_rank,
                fused_score=score,
            )
            for score, chunk, vector_rank, bm25_rank in scored[:top_k]
        ]

    def _ranks_by_id(self, results: list[RagChunk]) -> dict[UUID, int]:
        return {chunk.id: rank for rank, chunk in enumerate(results, start=1)}

    def _rrf_score(self, rank: int | None) -> float:
        if rank is None:
            return 0.0
        return 1.0 / (_RRF_K + rank)
