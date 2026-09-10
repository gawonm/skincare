"""원점수를 보존하며 벡터·BM25 결과를 결정적인 RRF 순위로 합친다."""

from agent.rag.ports import EvidenceRetriever, HybridSearchBackend, TextEmbedder
from agent.rag.schemas import (
    EmbeddingRequest,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    HybridFusionRequest,
    HybridSearchRequest,
    LookupStatus,
    RagRetrievalPolicy,
    RetrievedChunk,
)


class HybridRetriever:
    def __init__(self, policy: RagRetrievalPolicy) -> None:
        self._policy = policy

    def fuse(self, request: HybridFusionRequest) -> list[RetrievedChunk]:
        merged: dict[str, RetrievedChunk] = {}
        for vector_search, hits in (
            (True, request.results.vector_results),
            (False, request.results.bm25_results),
        ):
            seen: set[str] = set()
            for hit in hits:
                chunk_id = hit.chunk.chunk_id
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
                if chunk_id not in merged:
                    merged[chunk_id] = hit.model_copy(deep=True, update={"fused_score": 0.0})
                result = merged[chunk_id]
                if result.chunk != hit.chunk:
                    raise ValueError(
                        f"동일 청크 ID의 원문·출처가 검색 경로마다 다릅니다: {chunk_id}"
                    )
                result.fused_score += 1.0 / (self._policy.rrf_k + len(seen))
                if vector_search:
                    result.vector_similarity = hit.vector_similarity
                else:
                    result.bm25_relevance = hit.bm25_relevance
        return sorted(merged.values(), key=lambda hit: (-hit.fused_score, hit.chunk.chunk_id))[
            : request.limit
        ]


class HybridEvidenceRetriever(EvidenceRetriever):
    def __init__(
        self, backend: HybridSearchBackend, embedder: TextEmbedder, policy: RagRetrievalPolicy
    ) -> None:
        self._backend = backend
        self._embedder = embedder
        self._policy = policy
        self._fusion = HybridRetriever(policy)

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        embedding = await self._embedder.embed(EmbeddingRequest(texts=[request.query]))
        if len(embedding.vectors) != 1:
            raise ValueError("검색 질문 하나에 대응하는 임베딩 하나가 필요합니다.")
        merged: dict[str, RetrievedChunk] = {}
        # 성분별 순위를 따로 계산해야 나열 순서가 뒤인 성분을 불리하게 만들지 않는다.
        targets = sorted(set(request.target_ids)) or [None]
        for target_id in targets:
            scoped = request.model_copy(
                deep=True, update={"target_ids": [target_id] if target_id is not None else []}
            )
            result = await self._backend.search(
                HybridSearchRequest(
                    request=scoped, vector=embedding.vectors[0], embedding_model=embedding.model
                )
            )
            if result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
                return EvidenceSearchResult(
                    status=result.status, error_message=result.error_message
                )
            if result.status is LookupStatus.NO_RESULTS:
                continue
            for hit in self._fusion.fuse(HybridFusionRequest(results=result, limit=request.limit)):
                if target_id is not None and target_id not in hit.chunk.evidence.target_ids:
                    continue
                previous = merged.get(hit.chunk.chunk_id)
                if previous is not None and previous.chunk != hit.chunk:
                    raise ValueError("성분별 검색에서 동일 청크 ID의 출처가 서로 다릅니다.")
                if previous is None or hit.fused_score > previous.fused_score:
                    merged[hit.chunk.chunk_id] = hit
        chunks = sorted(merged.values(), key=lambda hit: (-hit.fused_score, hit.chunk.chunk_id))
        if not request.target_ids:
            # 문서의 신뢰도와 질문 관련성은 서로 다른 축이다.
            chunks = [
                hit
                for hit in chunks
                if hit.vector_similarity is not None
                and hit.vector_similarity >= self._policy.free_text_min_vector_similarity
            ]
        # 여러 대상은 각 대상의 top-k를 유지해 한 성분의 자료가 모두 밀려나지 않게 한다.
        records = {hit.chunk.evidence.evidence_id: hit.chunk.evidence for hit in chunks}
        return EvidenceSearchResult(
            status=LookupStatus.SUCCESS if records else LookupStatus.NO_RESULTS,
            records=list(records.values()),
            chunks=chunks,
        )
