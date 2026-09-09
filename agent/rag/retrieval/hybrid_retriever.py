"""벡터 검색과 BM25 검색 결과를 하나의 순위로 합친다(reciprocal rank fusion).

실제 벡터/BM25 쿼리는 `backend/repositories/rag_chunk_repository.py`(`RagChunkRepository`)가
실행한다 - SQLAlchemy 쿼리는 repositories에만 쓴다는 STRUCTURE.md 규칙 때문이다. 이 클래스는
이미 각각 랭킹까지 끝난 `(RagChunk, 원점수)` 목록 두 개(순수 데이터)만 받아 병합 계산만
한다 - 세션도 리포지토리도 직접 만들지 않는다.

원점수(코사인 유사도, BM25 점수)를 같이 받는 이유: RRF 순위만으로는 "얼마나" 관련 있는지
모른다 - 무관한 질문이라도 상대적으로 제일 가까운 결과에는 순위 1등이 붙는다. 자유 텍스트
질문의 관련성 판정(`RagQueryService`)은 이 원점수를 봐야 한다.
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
        self,
        vector_results: list[tuple[RagChunk, float]],
        bm25_results: list[tuple[RagChunk, float]],
        top_k: int,
    ) -> list[RetrievedChunk]:
        vector_ranks, vector_scores = self._ranks_and_scores(vector_results)
        bm25_ranks, bm25_scores = self._ranks_and_scores(bm25_results)
        chunks_by_id = {chunk.id: chunk for chunk, _ in (*vector_results, *bm25_results)}

        scored: list[tuple[float, RagChunk, int | None, int | None]] = []
        for chunk_id, chunk in chunks_by_id.items():
            vector_rank = vector_ranks.get(chunk_id)
            bm25_rank = bm25_ranks.get(chunk_id)
            score = self._rrf_score(vector_rank) + self._rrf_score(bm25_rank)
            scored.append((score, chunk, vector_rank, bm25_rank))

        # 동점일 때 정렬 순서가 입력 순서(=호출부가 어떤 순서로 검색했는지)에 좌우되지
        # 않도록 chunk id를 2차 정렬 키로 둔다(2026-09-10, 성분 순서 편향 수정과 같은 이유).
        scored.sort(key=lambda item: (-item[0], str(item[1].id)))

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
                vector_similarity=vector_scores.get(chunk.id),
                bm25_relevance=bm25_scores.get(chunk.id),
            )
            for score, chunk, vector_rank, bm25_rank in scored[:top_k]
        ]

    def _ranks_and_scores(
        self, results: list[tuple[RagChunk, float]]
    ) -> tuple[dict[UUID, int], dict[UUID, float]]:
        ranks = {chunk.id: rank for rank, (chunk, _) in enumerate(results, start=1)}
        scores = {chunk.id: score for chunk, score in results}
        return ranks, scores

    def _rrf_score(self, rank: int | None) -> float:
        if rank is None:
            return 0.0
        return 1.0 / (_RRF_K + rank)
