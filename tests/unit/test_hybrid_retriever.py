from typing import ClassVar

from agent.rag.ports import HybridSearchBackend, TextEmbedder
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever, HybridRetriever
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingVector,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    EvidenceSourceLane,
    EvidenceSourceType,
    HybridFusionRequest,
    HybridSearchRequest,
    HybridSearchResult,
    LookupStatus,
    RagChunkDraft,
    RagRetrievalPolicy,
    RetrievedChunk,
)


class SourcePolicyEmbedder(TextEmbedder):
    MODEL: ClassVar[str] = "source-policy-test"

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            model=self.MODEL,
            vectors=[EmbeddingVector(values=[1.0, 0.0]) for _ in request.texts],
        )


class SourceAwareBackend(HybridSearchBackend):
    def __init__(self, chunks: list[RagChunkDraft]) -> None:
        self._chunks = chunks
        self.requests: list[HybridSearchRequest] = []

    async def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        self.requests.append(request.model_copy(deep=True))
        source_plan = request.request.source_plan
        if source_plan is None:
            raise ValueError("테스트 검색 요청에 출처 계획이 없습니다.")
        allowed = set(source_plan.primary_source_types)
        hits = [
            RetrievedChunk(chunk=chunk, vector_similarity=0.9, bm25_relevance=1.0)
            for chunk in self._chunks
            if chunk.evidence.source_type in allowed
            and (
                not request.request.target_ids
                or set(request.request.target_ids).intersection(chunk.evidence.target_ids)
            )
        ]
        return HybridSearchResult(
            status=LookupStatus.SUCCESS if hits else LookupStatus.NO_RESULTS,
            vector_results=hits,
            bm25_results=list(reversed(hits)),
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


class TestEvidenceSourcePolicy:
    TARGET_ID: ClassVar[str] = "ingredient-a"

    def _chunk(self, chunk_id: str, source_type: EvidenceSourceType) -> RagChunkDraft:
        return RagChunkDraft(
            chunk_id=chunk_id,
            field_id="content",
            content=f"{source_type.value} 자료",
            evidence=EvidenceRecord(
                evidence_id=f"evidence-{chunk_id}",
                source_id=f"source-{chunk_id}",
                source_title=f"{source_type.value} 출처",
                source_type=source_type,
                text=f"{source_type.value} 자료",
                locator=f"test:{chunk_id}",
                target_ids=[self.TARGET_ID],
                review_status=EvidenceReviewStatus.UNREVIEWED,
                is_demo=False,
            ),
        )

    def _retriever(self, backend: HybridSearchBackend) -> HybridEvidenceRetriever:
        return HybridEvidenceRetriever(
            backend=backend,
            embedder=SourcePolicyEmbedder(),
            policy=RagRetrievalPolicy(free_text_min_vector_similarity=0.0),
        )

    async def test_efficacy_search_uses_pubmed_and_cir_sources(self) -> None:
        backend = SourceAwareBackend(
            [
                self._chunk("paper", EvidenceSourceType.PAPER),
                self._chunk("cir", EvidenceSourceType.CIR),
                self._chunk("mfds", EvidenceSourceType.MFDS),
            ]
        )

        result = await self._retriever(backend).search(
            EvidenceSearchRequest(
                query="피지 조절 효능을 알려줘",
                target_ids=[self.TARGET_ID],
            )
        )

        plan = backend.requests[0].request.source_plan
        assert plan is not None
        assert plan.lane is EvidenceSourceLane.EFFICACY
        assert plan.primary_source_types == [EvidenceSourceType.PAPER, EvidenceSourceType.CIR]
        assert {record.source_type for record in result.records} == {
            EvidenceSourceType.PAPER,
            EvidenceSourceType.CIR,
        }

    async def test_safety_search_uses_cir_and_pubmed_sources(self) -> None:
        backend = SourceAwareBackend(
            [
                self._chunk("paper", EvidenceSourceType.PAPER),
                self._chunk("cir", EvidenceSourceType.CIR),
                self._chunk("mfds", EvidenceSourceType.MFDS),
            ]
        )

        await self._retriever(backend).search(
            EvidenceSearchRequest(
                query="사용 시 주의사항과 자극 가능성을 알려줘",
                target_ids=[self.TARGET_ID],
            )
        )

        plan = backend.requests[0].request.source_plan
        assert plan is not None
        assert plan.lane is EvidenceSourceLane.SAFETY
        assert plan.primary_source_types == [EvidenceSourceType.CIR, EvidenceSourceType.PAPER]

    async def test_regulation_search_fills_mfds_shortage_with_cir_and_pubmed(self) -> None:
        backend = SourceAwareBackend(
            [
                self._chunk("mfds", EvidenceSourceType.MFDS),
                self._chunk("cir", EvidenceSourceType.CIR),
                self._chunk("paper", EvidenceSourceType.PAPER),
            ]
        )

        result = await self._retriever(backend).search(
            EvidenceSearchRequest(
                query="국내 사용제한과 배합 한도를 알려줘",
                target_ids=[self.TARGET_ID],
                limit=3,
            )
        )

        assert len(backend.requests) == 2
        primary = backend.requests[0].request.source_plan
        fallback = backend.requests[1].request.source_plan
        assert primary is not None and fallback is not None
        assert primary.lane is EvidenceSourceLane.REGULATION
        assert primary.primary_source_types == [EvidenceSourceType.MFDS]
        assert fallback.primary_source_types == [
            EvidenceSourceType.CIR,
            EvidenceSourceType.PAPER,
        ]
        assert [record.source_type for record in result.records] == [
            EvidenceSourceType.MFDS,
            EvidenceSourceType.CIR,
            EvidenceSourceType.PAPER,
        ]
