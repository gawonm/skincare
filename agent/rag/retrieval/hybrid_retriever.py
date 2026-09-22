"""원점수를 보존하며 벡터·BM25 결과를 결정적인 RRF 순위로 합친다."""

from agent.rag.ports import EvidenceReranker, EvidenceRetriever, HybridSearchBackend, TextEmbedder
from agent.rag.retrieval.evidence_source_policy import EvidenceSourcePolicy
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingVector,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    EvidenceSourcePlan,
    EvidenceSourceType,
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
        self._source_policy = EvidenceSourcePolicy()

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        embedding = await self._embedder.embed(EmbeddingRequest(texts=[request.query]))
        if len(embedding.vectors) != 1:
            raise ValueError("검색 질문 하나에 대응하는 임베딩 하나가 필요합니다.")
        source_plan = self._source_policy.resolve(request)
        planned_request = request.model_copy(deep=True, update={"source_plan": source_plan})
        merged: dict[str, RetrievedChunk] = {}
        source_priorities: dict[str, int] = {}
        reranker_model: str | None = None
        # 성분별 순위를 따로 계산해야 나열 순서가 뒤인 성분을 불리하게 만들지 않는다.
        targets = sorted(set(request.target_ids)) or [None]
        for target_id in targets:
            primary = await self._search_target(
                request=planned_request,
                target_id=target_id,
                query_vector=embedding.vectors[0],
                embedding_model=embedding.model,
                source_types=source_plan.primary_source_types,
                final_limit=request.limit,
            )
            if primary.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
                return EvidenceSearchResult(
                    status=primary.status, error_message=primary.error_message
                )
            reranker_model = self._merge_search_result(
                merged=merged,
                source_priorities=source_priorities,
                result=primary,
                source_priority=0,
                current_reranker_model=reranker_model,
            )
            remaining = request.limit - len(primary.chunks)
            if remaining <= 0 or not source_plan.fallback_source_types:
                continue
            fallback = await self._search_target(
                request=planned_request,
                target_id=target_id,
                query_vector=embedding.vectors[0],
                embedding_model=embedding.model,
                source_types=source_plan.fallback_source_types,
                final_limit=remaining,
            )
            if fallback.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
                return EvidenceSearchResult(
                    status=fallback.status, error_message=fallback.error_message
                )
            reranker_model = self._merge_search_result(
                merged=merged,
                source_priorities=source_priorities,
                result=fallback,
                source_priority=1,
                current_reranker_model=reranker_model,
            )
        chunks = sorted(
            merged.values(),
            key=lambda hit: (
                source_priorities[hit.chunk.chunk_id],
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

    async def _search_target(
        self,
        request: EvidenceSearchRequest,
        target_id: str | None,
        query_vector: EmbeddingVector,
        embedding_model: str,
        source_types: list[EvidenceSourceType],
        final_limit: int,
    ) -> EvidenceSearchResult:
        candidate_limit = (
            max(final_limit, self._policy.rerank_candidate_limit)
            if self._reranker is not None
            else final_limit
        )
        source_plan = request.source_plan
        if source_plan is None:
            raise ValueError("Evidence 출처 계획이 확정되지 않았습니다.")
        active_plan = EvidenceSourcePlan(
            lane=source_plan.lane,
            primary_source_types=source_types,
        )
        scoped = request.model_copy(
            deep=True,
            update={
                "target_ids": [target_id] if target_id is not None else [],
                "limit": candidate_limit,
                "source_plan": active_plan,
            },
        )
        result = await self._backend.search(
            HybridSearchRequest(
                request=scoped,
                vector=query_vector,
                embedding_model=embedding_model,
            )
        )
        if result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
            return EvidenceSearchResult(status=result.status, error_message=result.error_message)
        if result.status is LookupStatus.NO_RESULTS:
            return EvidenceSearchResult(status=LookupStatus.NO_RESULTS)
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
        reranker_model: str | None = None
        if self._reranker is not None and candidates:
            rerank_request = RerankRequest(
                query=request.query,
                candidates=candidates,
                limit=final_limit,
            )
            reranked = await self._reranker.rerank(rerank_request)
            self._validate_reranked(rerank_request, reranked)
            reranker_model = reranked.model
            candidates = reranked.chunks
        else:
            candidates = candidates[:final_limit]
        records = {hit.chunk.evidence.evidence_id: hit.chunk.evidence for hit in candidates}
        return EvidenceSearchResult(
            status=LookupStatus.SUCCESS if records else LookupStatus.NO_RESULTS,
            records=list(records.values()),
            chunks=candidates,
            reranker_model=reranker_model,
        )

    def _merge_search_result(
        self,
        merged: dict[str, RetrievedChunk],
        source_priorities: dict[str, int],
        result: EvidenceSearchResult,
        source_priority: int,
        current_reranker_model: str | None,
    ) -> str | None:
        if (
            result.reranker_model is not None
            and current_reranker_model is not None
            and result.reranker_model != current_reranker_model
        ):
            raise ValueError("출처별 검색 결과에 서로 다른 리랭커 모델이 사용되었습니다.")
        for hit in result.chunks:
            chunk_id = hit.chunk.chunk_id
            previous = merged.get(chunk_id)
            if previous is not None and previous.chunk != hit.chunk:
                raise ValueError("성분별 검색에서 동일 청크 ID의 출처가 서로 다릅니다.")
            previous_priority = source_priorities.get(chunk_id)
            if (
                previous is None
                or previous_priority is None
                or source_priority < previous_priority
                or (source_priority == previous_priority and self._is_better(hit, previous))
            ):
                merged[chunk_id] = hit
                source_priorities[chunk_id] = source_priority
        return result.reranker_model or current_reranker_model

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
