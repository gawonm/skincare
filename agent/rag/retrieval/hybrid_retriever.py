"""원점수를 보존하며 벡터·BM25 결과를 결정적인 RRF 순위로 합친다."""

from agent.rag.ports import EvidenceReranker, EvidenceRetriever, HybridSearchBackend, TextEmbedder
from agent.rag.schemas import (
    EmbeddingRequest,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    HybridFusionRequest,
    HybridSearchRequest,
    LookupStatus,
    RagRetrievalPolicy,
    RerankRequest,
    RerankResult,
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
        self,
        backend: HybridSearchBackend,
        embedder: TextEmbedder,
        policy: RagRetrievalPolicy,
        reranker: EvidenceReranker | None = None,
    ) -> None:
        self._backend = backend
        self._embedder = embedder
        self._policy = policy
        self._reranker = reranker
        self._fusion = HybridRetriever(policy)

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        embedding = await self._embedder.embed(EmbeddingRequest(texts=[request.query]))
        if len(embedding.vectors) != 1:
            raise ValueError("검색 질문 하나에 대응하는 임베딩 하나가 필요합니다.")
        merged: dict[str, RetrievedChunk] = {}
        reranker_model: str | None = None
        candidate_limit = (
            max(request.limit, self._policy.rerank_candidate_limit)
            if self._reranker is not None
            else request.limit
        )
        # 성분별 순위를 따로 계산해야 나열 순서가 뒤인 성분을 불리하게 만들지 않는다.
        targets = sorted(set(request.target_ids)) or [None]
        for target_id in targets:
            scoped = request.model_copy(
                deep=True,
                update={
                    "target_ids": [target_id] if target_id is not None else [],
                    "limit": candidate_limit,
                },
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
            candidates = self._fusion.fuse(
                HybridFusionRequest(results=result, limit=candidate_limit)
            )
            candidates = [
                hit
                for hit in candidates
                if target_id is None or target_id in hit.chunk.evidence.target_ids
            ]
            if target_id is None:
                # 임계값을 먼저 적용해야 관련 후보가 리랭커 top-k 밖으로 밀려 유실되지 않는다.
                candidates = [
                    hit
                    for hit in candidates
                    if hit.vector_similarity is not None
                    and hit.vector_similarity >= self._policy.free_text_min_vector_similarity
                ]
            if self._reranker is not None and candidates:
                rerank_request = RerankRequest(
                    query=request.query,
                    candidates=candidates,
                    limit=request.limit,
                )
                reranked = await self._reranker.rerank(rerank_request)
                self._validate_reranked(rerank_request, reranked)
                if reranker_model is not None and reranker_model != reranked.model:
                    raise ValueError("대상별 검색 결과에 서로 다른 리랭커 모델이 사용되었습니다.")
                reranker_model = reranked.model
                candidates = reranked.chunks
            else:
                candidates = candidates[: request.limit]
            for hit in candidates:
                if target_id is not None and target_id not in hit.chunk.evidence.target_ids:
                    continue
                previous = merged.get(hit.chunk.chunk_id)
                if previous is not None and previous.chunk != hit.chunk:
                    raise ValueError("성분별 검색에서 동일 청크 ID의 출처가 서로 다릅니다.")
                if previous is None or self._is_better(hit, previous):
                    merged[hit.chunk.chunk_id] = hit
        chunks = sorted(
            merged.values(),
            key=lambda hit: (
                hit.reranker_score is None,
                -(hit.reranker_score if hit.reranker_score is not None else 0.0),
                -hit.fused_score,
                hit.chunk.chunk_id,
            ),
        )
        # 여러 대상은 각 대상의 top-k를 유지해 한 성분의 자료가 모두 밀려나지 않게 한다.
        records = {hit.chunk.evidence.evidence_id: hit.chunk.evidence for hit in chunks}
        return EvidenceSearchResult(
            status=LookupStatus.SUCCESS if records else LookupStatus.NO_RESULTS,
            records=list(records.values()),
            chunks=chunks,
            reranker_model=reranker_model,
        )

    def _validate_reranked(self, request: RerankRequest, result: RerankResult) -> None:
        expected_ids = {candidate.chunk.chunk_id for candidate in request.candidates}
        actual_ids = [candidate.chunk.chunk_id for candidate in result.chunks]
        if len(actual_ids) != len(set(actual_ids)):
            raise ValueError("리랭커 결과에 동일 청크 ID가 중복되었습니다.")
        if any(chunk_id not in expected_ids for chunk_id in actual_ids):
            raise ValueError("리랭커가 1차 검색 후보에 없던 청크를 반환했습니다.")
        if len(result.chunks) > request.limit:
            raise ValueError("리랭커 결과가 요청한 최종 검색 개수를 초과했습니다.")
        if any(candidate.reranker_score is None for candidate in result.chunks):
            raise ValueError("리랭커 결과에 관련도 점수가 누락되었습니다.")

    def _is_better(self, candidate: RetrievedChunk, previous: RetrievedChunk) -> bool:
        if (
            candidate.reranker_score is not None
            and previous.reranker_score is not None
            and candidate.reranker_score != previous.reranker_score
        ):
            return candidate.reranker_score > previous.reranker_score
        return candidate.fused_score > previous.fused_score
