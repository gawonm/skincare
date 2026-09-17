"""최신 2-Layer DB 조회를 기존 Agent 포트로 변환하는 읽기 전용 어댑터."""

from collections.abc import Sequence
from typing import ClassVar
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.ports import IngredientRepository, ProductRepository
from agent.rag.claim_schemas import (
    ClaimHit,
    ClaimIngestionDecision,
    ClaimIngredientMatchingStatus,
    ClaimIngredientRef,
    ClaimSearchRequest,
    ClaimSearchResult,
    ClaimStatementType,
    ClaimSupportStatus,
)
from agent.rag.ports import ClaimRetriever, HybridSearchBackend, TextEmbedder
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingRequest,
    EmbeddingVector,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceScope,
    EvidenceSourceType,
    EvidenceTextKind,
    HybridSearchRequest,
    HybridSearchResult,
    IngredientRecord,
    IngredientResolveRequest,
    IngredientResolveResult,
    LocalEmbeddingModel,
    LookupStatus,
    ProductCategory,
    ProductGetRequest,
    ProductGetResult,
    ProductRecord,
    ProductSearchRequest,
    ProductSearchResult,
    QuestionIntent,
    RagChunkDraft,
    RagConfidenceTier,
    RetrievedChunk,
)
from backend.repositories.agent_ingredient_repository import (
    AgentIngredientReadRepository,
    IngredientLookupRow,
)
from backend.repositories.agent_product_repository import (
    AgentProductReadRepository,
    AgentProductRow,
)
from backend.repositories.claim_search_repository import (
    ClaimIngredientRow,
    ClaimSearchRepository,
    ClaimSearchRow,
    ClaimVectorSearchRequest,
)
from backend.repositories.evidence_search_repository import (
    EvidenceSearchRepository,
    EvidenceSearchRow,
    EvidenceTextSearchRequest,
    EvidenceVectorSearchRequest,
)


class TwoLayerClaimRetriever(ClaimRetriever):
    """BGE-M3 질의 벡터로 운영 검색 허용 Claim만 반환한다."""

    _QUERY_SEPARATOR: ClassVar[str] = " "

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: TextEmbedder,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder

    @property
    def embedding_model(self) -> LocalEmbeddingModel:
        return LocalEmbeddingModel.BGE_M3

    async def search(self, request: ClaimSearchRequest) -> ClaimSearchResult:
        query = self._QUERY_SEPARATOR.join([request.query, *request.skin_concerns]).strip()
        try:
            if request.query_embedding is None:
                embedding = await self._embedder.embed(EmbeddingRequest(texts=[query]))
                model = embedding.model
                vectors = embedding.vectors
            else:
                model = self.embedding_model.value
                vectors = [request.query_embedding]
            unsupported = self._embedding_error(model, vectors)
            if unsupported is not None:
                return ClaimSearchResult(
                    status=LookupStatus.UNSUPPORTED,
                    error_message=unsupported,
                )
            async with self._session_factory() as session:
                rows = await ClaimSearchRepository(session).search_by_vector(
                    ClaimVectorSearchRequest(
                        query_vector=vectors[0].values,
                        embedding_model=model,
                        annotation_version=request.annotation_version,
                        statement_types=list(ClaimSearchRepository.SUPPORTED_STATEMENT_TYPES),
                        ingredient_ids=[
                            UUID(ingredient_id) for ingredient_id in request.ingredient_ids
                        ],
                        limit=request.top_k,
                    )
                )
            hits = [self._to_hit(row) for row in rows]
        except (SQLAlchemyError, RuntimeError, ValueError, ValidationError) as error:
            return ClaimSearchResult(
                status=LookupStatus.ERROR,
                error_message=f"Claim 검색 또는 DTO 변환에 실패했습니다: {error}",
            )
        if not hits:
            return ClaimSearchResult(status=LookupStatus.NO_RESULTS)
        return ClaimSearchResult(status=LookupStatus.SUCCESS, hits=hits)

    def _embedding_error(self, model: str, vectors: Sequence[EmbeddingVector]) -> str | None:
        if model != self.embedding_model.value:
            return (
                "Claim 저장 벡터와 질의 임베딩 모델이 다릅니다: "
                f"expected={self.embedding_model.value}, actual={model}"
            )
        if len(vectors) != 1:
            return f"Claim 질의 하나에 임베딩 하나가 필요합니다: actual={len(vectors)}"
        values = vectors[0].values
        if len(values) != BGE_M3_EMBEDDING_DIMENSIONS:
            return (
                "Claim 저장 벡터와 질의 임베딩 차원이 다릅니다: "
                f"expected={BGE_M3_EMBEDDING_DIMENSIONS}, actual={len(values)}"
            )
        return None

    def _to_hit(self, row: ClaimSearchRow) -> ClaimHit:
        return ClaimHit(
            claim_chunk_id=str(row.claim_chunk_id),
            statement_id=row.statement_id,
            statement_type=ClaimStatementType(row.statement_type.value),
            content=row.content,
            score=row.retrieval_score,
            ingredient_refs=[
                self._to_ingredient_ref(ingredient) for ingredient in row.ingredients
            ],
            source_record_id=row.source_record_id,
            annotation_version=row.annotation_version,
            decision=ClaimIngestionDecision(row.decision.value),
            support_status=ClaimSupportStatus(row.support_status.value),
        )

    def _to_ingredient_ref(self, row: ClaimIngredientRow) -> ClaimIngredientRef:
        return ClaimIngredientRef(
            raw_name=row.raw_name,
            ingredient_id=str(row.ingredient_id) if row.ingredient_id is not None else None,
            matching_status=ClaimIngredientMatchingStatus(row.matching_status.value),
        )


class EvidenceTopicIntentMapper:
    """Evidence topic을 LLM 없이 질문 축으로 변환한다."""

    _TOPIC_MAP: ClassVar[dict[str, QuestionIntent]] = {
        "barrier": QuestionIntent.EFFICACY,
        "sebum_control": QuestionIntent.EFFICACY,
        "pigmentation": QuestionIntent.EFFICACY,
        "efficacy": QuestionIntent.EFFICACY,
        "safety": QuestionIntent.PRECAUTION,
        "precaution": QuestionIntent.PRECAUTION,
        "concentration": QuestionIntent.CONCENTRATION,
        "regulation": QuestionIntent.REGULATION,
        "usage": QuestionIntent.USAGE_FREQUENCY,
        "combination": QuestionIntent.COMBINATION,
    }

    def map(self, topics: list[str]) -> list[QuestionIntent]:
        return list(
            dict.fromkeys(
                intent
                for topic in topics
                if (intent := self._TOPIC_MAP.get(topic.casefold())) is not None
            )
        )


class TwoLayerEvidenceSearchBackend(HybridSearchBackend):
    """Evidence 전용 vector/text 검색 결과를 Agent 하이브리드 검색 DTO로 변환한다."""

    _SOURCE_TYPES: ClassVar[dict[str, EvidenceSourceType]] = {
        "pubmed_abstract": EvidenceSourceType.PAPER,
        "mfds": EvidenceSourceType.MFDS,
        "cir": EvidenceSourceType.CIR,
    }
    _VERIFIED_STATUS: ClassVar[str] = "verified"
    _PEER_REVIEWED_LEVEL: ClassVar[str] = "peer_reviewed_study"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._intent_mapper = EvidenceTopicIntentMapper()

    async def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        unsupported = self._unsupported_reason(request)
        if unsupported is not None:
            return HybridSearchResult(
                status=LookupStatus.UNSUPPORTED,
                error_message=unsupported,
            )
        try:
            target_ids = [UUID(target_id) for target_id in request.request.target_ids]
            async with self._session_factory() as session:
                repository = EvidenceSearchRepository(session)
                vector_rows = await repository.search_by_vector(
                    EvidenceVectorSearchRequest(
                        query_vector=request.vector.values,
                        embedding_model=request.embedding_model,
                        target_ids=target_ids,
                        limit=request.request.limit,
                    )
                )
                text_rows = await repository.search_by_text(
                    EvidenceTextSearchRequest(
                        query_text=request.request.query,
                        embedding_model=request.embedding_model,
                        target_ids=target_ids,
                        limit=request.request.limit,
                    )
                )
            vector_results = [self._to_retrieved(row, vector=True) for row in vector_rows]
            text_results = [self._to_retrieved(row, vector=False) for row in text_rows]
        except (SQLAlchemyError, RuntimeError, ValueError, ValidationError) as error:
            return HybridSearchResult(
                status=LookupStatus.ERROR,
                error_message=f"Evidence 검색 또는 DTO 변환에 실패했습니다: {error}",
            )
        if not vector_results and not text_results:
            return HybridSearchResult(status=LookupStatus.NO_RESULTS)
        return HybridSearchResult(
            status=LookupStatus.SUCCESS,
            vector_results=vector_results,
            bm25_results=text_results,
        )

    def _unsupported_reason(self, request: HybridSearchRequest) -> str | None:
        if request.embedding_model != LocalEmbeddingModel.BGE_M3.value:
            return (
                "Evidence 저장 벡터와 질의 임베딩 모델이 다릅니다: "
                f"expected={LocalEmbeddingModel.BGE_M3.value}, actual={request.embedding_model}"
            )
        if len(request.vector.values) != BGE_M3_EMBEDDING_DIMENSIONS:
            return (
                "Evidence 저장 벡터와 질의 임베딩 차원이 다릅니다: "
                f"expected={BGE_M3_EMBEDDING_DIMENSIONS}, actual={len(request.vector.values)}"
            )
        try:
            for target_id in request.request.target_ids:
                UUID(target_id)
        except ValueError:
            return "Evidence 대상 ID는 UUID여야 합니다."
        return None

    def _to_retrieved(self, row: EvidenceSearchRow, vector: bool) -> RetrievedChunk:
        record = self._to_record(row)
        confidence = (
            RagConfidenceTier.STRUCTURED_KNOWLEDGE
            if row.evidence_level == self._PEER_REVIEWED_LEVEL
            else RagConfidenceTier.UNKNOWN
        )
        draft = RagChunkDraft(
            chunk_id=row.chunk_id,
            field_id=row.section,
            content=row.content,
            evidence=record,
            intents=self._intent_mapper.map(row.claim_topics),
            confidence_tier=confidence,
        )
        if vector:
            return RetrievedChunk(chunk=draft, vector_similarity=row.score)
        return RetrievedChunk(chunk=draft, bm25_relevance=row.score)

    def _to_record(self, row: EvidenceSearchRow) -> EvidenceRecord:
        source_type = self._SOURCE_TYPES.get(
            row.document_source_type.casefold(), EvidenceSourceType.UNKNOWN
        )
        review_status = (
            EvidenceReviewStatus.VERIFIED
            if row.document_status is not None
            and row.document_status.casefold() == self._VERIFIED_STATUS
            else EvidenceReviewStatus.UNREVIEWED
        )
        target_ids = [str(target_id) for target_id in row.target_ids]
        scope = EvidenceScope.INGREDIENT if len(target_ids) == 1 else EvidenceScope.ASSOCIATION
        return EvidenceRecord(
            source_type=source_type,
            text_kind=EvidenceTextKind.EXCERPT,
            scope=scope,
            topic=", ".join(row.claim_topics) or None,
            jurisdiction=row.jurisdiction,
            source_reference=self._source_reference(row),
            published_at=row.document_date.isoformat() if row.document_date is not None else None,
            collected_at=row.retrieved_at.isoformat(),
            evidence_id=str(row.evidence_id),
            source_id=row.source_id,
            source_title=row.source_title,
            text=row.content,
            locator=f"{row.section}:{row.chunk_index}",
            target_ids=target_ids,
            conditions=EvidenceConditions(
                formulation=row.formulation_type,
                jurisdiction=row.jurisdiction,
            ),
            review_status=review_status,
            url=row.chunk_url or row.document_url,
            is_demo=False,
        )

    def _source_reference(self, row: EvidenceSearchRow) -> str | None:
        references = [
            reference
            for reference in (
                f"PMID:{row.chunk_pmid or row.document_pmid}"
                if row.chunk_pmid or row.document_pmid
                else None,
                f"DOI:{row.chunk_doi or row.document_doi}"
                if row.chunk_doi or row.document_doi
                else None,
            )
            if reference is not None
        ]
        return "; ".join(references) or None


class TwoLayerIngredientRepository(IngredientRepository):
    """`ingredient_master`의 확정 이름만 Agent 성분 식별 결과로 노출한다."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        try:
            async with self._session_factory() as session:
                rows = await AgentIngredientReadRepository(session).find_exact(
                    request.name.strip()
                )
            ingredients = [self._to_record(row) for row in rows]
        except (SQLAlchemyError, RuntimeError, ValueError, ValidationError) as error:
            return IngredientResolveResult(
                status=LookupStatus.ERROR,
                error_message=f"성분 식별 조회에 실패했습니다: {error}",
            )
        if not ingredients:
            return IngredientResolveResult(status=LookupStatus.NO_RESULTS)
        if len(ingredients) == 1:
            return IngredientResolveResult(
                status=LookupStatus.SUCCESS,
                ingredient=ingredients[0],
            )
        return IngredientResolveResult(
            status=LookupStatus.SUCCESS,
            ambiguous_candidates=ingredients,
        )

    def _to_record(self, row: IngredientLookupRow) -> IngredientRecord:
        aliases = list(
            dict.fromkeys(
                alias
                for alias in [row.standard_name_en, *row.old_names_ko, *row.old_names_en]
                if alias
            )
        )
        return IngredientRecord(
            ingredient_id=str(row.ingredient_id),
            canonical_name=row.canonical_name,
            ingredient_code=row.ingredient_code,
            source_version=row.source_version,
            aliases=aliases,
            is_demo=False,
        )


class TwoLayerProductRepository(ProductRepository):
    """confirmed 성분 연결이 있는 상품만 Agent 추천 후보로 노출한다."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        if not request.filters.ingredient_ids:
            return ProductSearchResult(
                status=LookupStatus.UNSUPPORTED,
                unsupported_conditions=["2-Layer smoke 상품 검색은 성분 ID 필터가 필요합니다."],
            )
        try:
            ingredient_ids = [UUID(ingredient_id) for ingredient_id in request.filters.ingredient_ids]
        except ValueError:
            return ProductSearchResult(
                status=LookupStatus.UNSUPPORTED,
                unsupported_conditions=["상품 검색의 성분 ID는 UUID여야 합니다."],
            )
        try:
            async with self._session_factory() as session:
                rows = await AgentProductReadRepository(session).search_by_ingredients(
                    ingredient_ids,
                    request.limit,
                )
            products = [self._to_record(row) for row in rows]
        except (SQLAlchemyError, RuntimeError, ValueError, ValidationError) as error:
            return ProductSearchResult(
                status=LookupStatus.ERROR,
                error_message=f"confirmed 상품 조회에 실패했습니다: {error}",
            )
        return ProductSearchResult(
            status=LookupStatus.SUCCESS if products else LookupStatus.NO_RESULTS,
            products=products,
        )

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        if request.version is not None:
            return ProductGetResult(
                status=LookupStatus.UNSUPPORTED,
                error_message="현재 dump 상품 조회는 별도 version 필터를 지원하지 않습니다.",
            )
        try:
            product_id = UUID(request.product_id)
        except ValueError:
            return ProductGetResult(
                status=LookupStatus.UNSUPPORTED,
                error_message="상품 ID는 UUID여야 합니다.",
            )
        try:
            async with self._session_factory() as session:
                row = await AgentProductReadRepository(session).get(product_id)
            product = self._to_record(row) if row is not None else None
        except (SQLAlchemyError, RuntimeError, ValueError, ValidationError) as error:
            return ProductGetResult(
                status=LookupStatus.ERROR,
                error_message=f"상품 상세 조회에 실패했습니다: {error}",
            )
        if product is None:
            return ProductGetResult(status=LookupStatus.NO_RESULTS)
        return ProductGetResult(status=LookupStatus.SUCCESS, product=product)

    def _to_record(self, row: AgentProductRow) -> ProductRecord:
        return ProductRecord(
            product_id=str(row.product_id),
            name=row.name,
            category=ProductCategory(code=row.category, name=row.category),
            ingredient_ids=[str(ingredient_id) for ingredient_id in row.ingredient_ids],
            source_id=f"{row.source}:{row.source_product_id}",
            checked_at=row.observed_at.isoformat(),
            is_demo=False,
        )
