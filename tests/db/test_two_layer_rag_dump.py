"""최신 dump를 복원한 DB와 2-Layer 읽기 어댑터의 통합 smoke."""

from typing import ClassVar

import pytest
from sqlalchemy.engine import make_url

from agent.claim_verification import ClaimEvidenceVerifier, IngredientRecommendationSelector
from agent.rag.claim_schemas import (
    ClaimAnnotationStatus,
    ClaimConfidence,
    ClaimResolvedTarget,
    ClaimSearchRequest,
    ClaimVerificationBundle,
    ClaimVerificationRequest,
    ClaimVerificationStatus,
    RecommendationBasis,
)
from agent.rag.pipeline import EvidenceApplicabilityEvaluator, EvidencePipeline
from agent.rag.ports import TextEmbedder
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingVector,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    IngredientResolveRequest,
    LocalEmbeddingModel,
    LookupStatus,
    ProductSearchFilters,
    ProductSearchRequest,
    RagRetrievalPolicy,
)
from backend.services.two_layer_rag_adapters import (
    TwoLayerClaimRetriever,
    TwoLayerEvidenceSearchBackend,
    TwoLayerIngredientRepository,
    TwoLayerProductRepository,
)
from core.config import settings
from core.database import Database, DatabaseConfig


class FixedBgeM3Embedder(TextEmbedder):
    """DB 계약만 검증할 때 외부 모델 다운로드를 피하는 1,024차원 test double."""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        values = [0.0] * BGE_M3_EMBEDDING_DIMENSIONS
        values[0] = 1.0
        return EmbeddingResult(
            model=LocalEmbeddingModel.BGE_M3.value,
            vectors=[EmbeddingVector(values=list(values)) for _ in request.texts],
        )


class LatestDumpDatabaseFactory:
    """공용 설정의 접속 정보는 유지하고 smoke DB 이름만 명시적으로 바꾼다."""

    DATABASE_NAME: ClassVar[str] = "skincare_latest"

    def create(self) -> Database:
        url = make_url(settings.database.url).set(database=self.DATABASE_NAME)
        return Database(
            DatabaseConfig(
                url=url.render_as_string(hide_password=False),
                model_modules=settings.database.model_modules,
            )
        )


@pytest.mark.integration
class TestTwoLayerRagLatestDump:
    """Claim 통과 후 미검수 Evidence가 Claim-only 상품으로 이어지는지 검증한다."""

    NIACINAMIDE_NAME: ClassVar[str] = "나이아신아마이드"

    async def test_unreviewed_evidence_keeps_claim_only_product_candidates(self) -> None:
        database = LatestDumpDatabaseFactory().create()
        embedder = FixedBgeM3Embedder()
        try:
            claims = await TwoLayerClaimRetriever(
                database.session_factory,
                embedder,
            ).search(
                ClaimSearchRequest(
                    query="피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?",
                    skin_concerns=["여드름/뾰루지"],
                    limit=5,
                )
            )

            assert claims.status is LookupStatus.SUCCESS
            assert len(claims.hits) == 5
            assert all(
                hit.annotation_status is ClaimAnnotationStatus.APPROVED
                for hit in claims.hits
            )
            assert all(hit.confidence is ClaimConfidence.LOW for hit in claims.hits)

            niacinamide = next(
                hit
                for hit in claims.hits
                if any(
                    anchor.raw_name == self.NIACINAMIDE_NAME
                    for anchor in hit.ingredient_anchors()
                )
            )
            ingredient_ids = niacinamide.matched_ingredient_ids()
            assert len(ingredient_ids) == 1
            resolved = await TwoLayerIngredientRepository(
                database.session_factory
            ).resolve(IngredientResolveRequest(name=self.NIACINAMIDE_NAME))
            assert resolved.status is LookupStatus.SUCCESS
            assert resolved.ingredient is not None
            assert resolved.ingredient.ingredient_id == ingredient_ids[0]

            evidence_retriever = HybridEvidenceRetriever(
                backend=TwoLayerEvidenceSearchBackend(database.session_factory),
                embedder=embedder,
                policy=RagRetrievalPolicy(
                    free_text_min_vector_similarity=-1.0,
                    rrf_k=60,
                    rerank_candidate_limit=30,
                ),
            )
            evidence = await evidence_retriever.search(
                EvidenceSearchRequest(
                    query=niacinamide.verification_query(),
                    target_ids=ingredient_ids,
                    limit=5,
                )
            )

            assert evidence.status is LookupStatus.SUCCESS
            assert len(evidence.records) == 3
            assert all(
                record.review_status is EvidenceReviewStatus.UNREVIEWED
                for record in evidence.records
            )

            verification = await ClaimEvidenceVerifier(
                EvidencePipeline(
                    retriever=evidence_retriever,
                    evaluator=EvidenceApplicabilityEvaluator(),
                )
            ).verify(
                ClaimVerificationRequest(
                    target=ClaimResolvedTarget(
                        statement_id=niacinamide.statement_id,
                        ingredient_ids=ingredient_ids,
                        query=niacinamide.verification_query(),
                    )
                )
            )

            assert verification.status is ClaimVerificationStatus.INSUFFICIENT
            recommendations = IngredientRecommendationSelector().select(
                ClaimVerificationBundle(results=[verification])
            )
            assert len(recommendations.candidates) == 1
            assert recommendations.candidates[0].basis is RecommendationBasis.CLAIM_ONLY

            products = await TwoLayerProductRepository(database.session_factory).search(
                ProductSearchRequest(
                    filters=ProductSearchFilters(ingredient_ids=ingredient_ids),
                    limit=5,
                )
            )
            assert products.status is LookupStatus.SUCCESS
            assert products.products
            assert len({product.product_id for product in products.products}) == len(
                products.products
            )
            assert all(
                ingredient_ids[0] in product.ingredient_ids
                for product in products.products
            )
        finally:
            await database.dispose()
