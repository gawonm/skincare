"""pgvector/BM25 저장소를 현재 Agent 하이브리드 검색 포트에 연결한다."""

from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.rag.ports import HybridSearchBackend
from agent.rag.schemas import (
    HybridSearchRequest,
    HybridSearchResult,
    LookupStatus,
    RagChunkDraft,
    RagConfidenceTier,
    RagDocument,
    RetrievedChunk,
)
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.ingredient_knowledge_fact_repository import (
    IngredientKnowledgeFactRepository,
)
from backend.repositories.rag_chunk_repository import (
    RagBm25SearchRequest,
    RagChunkRepository,
    RagChunkSearchHit,
    RagVectorSearchRequest,
)
from backend.services.rag_document_mapper import RagDocumentMapper
from models.rag_chunk import RagChunk, RagSourceTable


class SqlAlchemyHybridSearchBackend(HybridSearchBackend):
    """SQL은 repository에 위임하고 Agent DTO 변환과 상태 구분만 담당한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._chunks = RagChunkRepository(session)
        self._evidence = EvidenceRepository(session)
        self._knowledge = IngredientKnowledgeFactRepository(session)
        self._documents = RagDocumentMapper()

    async def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        try:
            target_ids = self._parse_target_ids(request.request.target_ids)
        except ValueError as error:
            return HybridSearchResult(
                status=LookupStatus.UNSUPPORTED,
                error_message=f"현재 RAG DB가 지원하지 않는 대상 ID입니다: {error}",
            )
        try:
            vector_hits = await self._chunks.search_by_vector(
                RagVectorSearchRequest(
                    query_vector=request.vector.values,
                    limit=request.request.limit,
                    target_ids=target_ids,
                    embedding_model=request.embedding_model,
                )
            )
            bm25_hits = await self._chunks.search_by_bm25(
                RagBm25SearchRequest(
                    query_text=request.request.query,
                    limit=request.request.limit,
                    target_ids=target_ids,
                    embedding_model=request.embedding_model,
                )
            )
            documents = await self._load_documents(vector_hits + bm25_hits)
            vector_results = [self._to_retrieved(hit, documents, True) for hit in vector_hits]
            bm25_results = [self._to_retrieved(hit, documents, False) for hit in bm25_hits]
        except (SQLAlchemyError, RuntimeError, ValueError) as error:
            return HybridSearchResult(
                status=LookupStatus.ERROR,
                error_message=f"RAG 검색 또는 근거 변환에 실패했습니다: {error}",
            )
        if not vector_results and not bm25_results:
            return HybridSearchResult(status=LookupStatus.NO_RESULTS)
        return HybridSearchResult(
            status=LookupStatus.SUCCESS,
            vector_results=vector_results,
            bm25_results=bm25_results,
        )

    def _parse_target_ids(self, target_ids: list[str]) -> list[UUID]:
        parsed: list[UUID] = []
        for target_id in target_ids:
            try:
                parsed.append(UUID(target_id))
            except ValueError as error:
                raise ValueError(target_id) from error
        return parsed

    async def _load_documents(self, hits: list[RagChunkSearchHit]) -> dict[str, RagDocument]:
        evidence_ids = sorted(
            {hit.chunk.evidence_id for hit in hits if hit.chunk.evidence_id is not None},
            key=str,
        )
        knowledge_ids = sorted(
            {
                hit.chunk.ingredient_knowledge_fact_id
                for hit in hits
                if hit.chunk.ingredient_knowledge_fact_id is not None
            },
            key=str,
        )
        evidence_documents = self._documents.evidence(
            await self._evidence.list_by_ids(evidence_ids)
        )
        knowledge_documents = self._documents.knowledge(
            await self._knowledge.list_by_ids(knowledge_ids)
        )
        documents = {
            document.evidence.evidence_id: document
            for document in evidence_documents + knowledge_documents
        }
        expected = {self._document_ref(hit.chunk) for hit in hits}
        missing = expected - documents.keys()
        if missing:
            raise RuntimeError(f"원본 근거를 찾을 수 없는 RAG 청크가 있습니다: {sorted(missing)}")
        return documents

    def _to_retrieved(
        self,
        hit: RagChunkSearchHit,
        documents: dict[str, RagDocument],
        vector_search: bool,
    ) -> RetrievedChunk:
        row = hit.chunk
        document = documents[self._document_ref(row)]
        fields = {field.field_id: field for field in document.fields}
        field = fields.get(row.chunk_field.value)
        if field is None:
            raise RuntimeError(
                f"원본에 없는 필드를 가리키는 RAG 청크입니다: {row.chunk_field.value}"
            )
        if field.content != row.content:
            raise RuntimeError(f"원본과 재색인 내용이 다른 RAG 청크입니다: {row.id}")
        draft = RagChunkDraft(
            chunk_id=str(row.id),
            field_id=row.chunk_field.value,
            content=row.content,
            evidence=document.evidence,
            intents=field.intents,
            confidence_tier=RagConfidenceTier(row.confidence_tier.value),
        )
        if vector_search:
            return RetrievedChunk(chunk=draft, vector_similarity=hit.score)
        return RetrievedChunk(chunk=draft, bm25_relevance=hit.score)

    def _document_ref(self, chunk: RagChunk) -> str:
        source_ref = chunk.evidence_id or chunk.ingredient_knowledge_fact_id
        if source_ref is None or chunk.source_table is RagSourceTable.NIA_QA:
            raise ValueError(f"현재 Agent 계약이 지원하지 않는 RAG 원본입니다: {chunk.id}")
        return str(source_ref)
