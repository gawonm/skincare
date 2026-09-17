"""최신 dump와 실제 BGE-M3를 사용하는 결정적 2-Layer DB smoke 실행기.

실행:
    uv run python -m tests.agent.two_layer_rag_dump_smoke

LLM은 호출하지 않는다. Claim/Evidence 검색, Claim-only 판정, confirmed 상품 연결만 검증한다.
"""

import asyncio
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import make_url

from agent.claim_verification import ClaimEvidenceVerifier, IngredientRecommendationSelector
from agent.rag.claim_schemas import (
    ClaimConfidence,
    ClaimResolvedTarget,
    ClaimSearchRequest,
    ClaimVerificationBundle,
    ClaimVerificationRequest,
    RecommendationBasis,
)
from agent.rag.embedding.local_embedder import LocalBgeM3Embedder
from agent.rag.pipeline import EvidenceApplicabilityEvaluator, EvidencePipeline
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.schemas import (
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    LocalEmbeddingConfig,
    LocalEmbeddingModel,
    LocalModelDevice,
    LookupStatus,
    ProductSearchFilters,
    ProductSearchRequest,
    RagRetrievalPolicy,
)
from backend.services.two_layer_rag_adapters import (
    TwoLayerClaimRetriever,
    TwoLayerEvidenceSearchBackend,
    TwoLayerProductRepository,
)
from core.config import settings
from core.database import Database, DatabaseConfig


class TwoLayerDumpSmokeReport(BaseModel):
    """사람과 자동화가 함께 확인할 수 있는 smoke 결과."""

    model_config = ConfigDict(frozen=True)

    database: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    claim_count: int = Field(ge=0)
    low_confidence_claim_count: int = Field(ge=0)
    evidence_record_count: int = Field(ge=0)
    unreviewed_evidence_count: int = Field(ge=0)
    claim_only_ingredient_count: int = Field(ge=0)
    claim_only_with_product_count: int = Field(ge=0)
    unique_product_sample_count: int = Field(ge=0)


class TwoLayerRagDumpSmokeRunner:
    """외부 LLM 없이 실제 BGE-M3와 복원 DB의 연결만 확인한다."""

    DATABASE_NAME: ClassVar[str] = "skincare_latest"
    QUERY: ClassVar[str] = "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"
    SKIN_CONCERNS: ClassVar[list[str]] = ["여드름/뾰루지"]
    NIACINAMIDE_NAME: ClassVar[str] = "나이아신아마이드"
    CLAIM_LIMIT: ClassVar[int] = 5
    PRODUCT_SAMPLE_LIMIT: ClassVar[int] = 10

    def __init__(self) -> None:
        self._database = self._create_database()
        self._embedder = LocalBgeM3Embedder(self._embedding_config())
        self._claims = TwoLayerClaimRetriever(
            self._database.session_factory,
            self._embedder,
        )
        self._evidence = HybridEvidenceRetriever(
            backend=TwoLayerEvidenceSearchBackend(self._database.session_factory),
            embedder=self._embedder,
            policy=RagRetrievalPolicy(
                # 성분 ID 필터 smoke에서는 자유 질의 임계값을 판정에 사용하지 않는다.
                free_text_min_vector_similarity=-1.0,
                rrf_k=settings.agent.retrieval.rrf_k,
                rerank_candidate_limit=settings.agent.retrieval.rerank_candidate_limit,
            ),
        )
        self._products = TwoLayerProductRepository(self._database.session_factory)

    async def run(self) -> TwoLayerDumpSmokeReport:
        try:
            claims = await self._claims.search(
                ClaimSearchRequest(
                    query=self.QUERY,
                    skin_concerns=self.SKIN_CONCERNS,
                    limit=self.CLAIM_LIMIT,
                )
            )
            if claims.status is not LookupStatus.SUCCESS:
                raise RuntimeError(
                    f"Claim smoke 검색 실패: status={claims.status.value}, "
                    f"error={claims.error_message}"
                )

            niacinamide = next(
                hit
                for hit in claims.hits
                if any(
                    anchor.raw_name == self.NIACINAMIDE_NAME
                    for anchor in hit.ingredient_anchors()
                )
            )
            niacinamide_ids = niacinamide.matched_ingredient_ids()
            evidence = await self._evidence.search(
                EvidenceSearchRequest(
                    query=niacinamide.verification_query(),
                    target_ids=niacinamide_ids,
                    limit=self.CLAIM_LIMIT,
                )
            )
            if evidence.status is not LookupStatus.SUCCESS:
                raise RuntimeError(
                    f"Evidence smoke 검색 실패: status={evidence.status.value}, "
                    f"error={evidence.error_message}"
                )

            verifier = ClaimEvidenceVerifier(
                EvidencePipeline(
                    retriever=self._evidence,
                    evaluator=EvidenceApplicabilityEvaluator(),
                )
            )
            verification = ClaimVerificationBundle(
                results=[
                    await verifier.verify(
                        ClaimVerificationRequest(
                            target=ClaimResolvedTarget(
                                statement_id=hit.statement_id,
                                ingredient_ids=hit.matched_ingredient_ids(),
                                query=hit.verification_query(),
                            )
                        )
                    )
                    for hit in claims.hits
                    if hit.matched_ingredient_ids()
                ]
            )
            recommendations = IngredientRecommendationSelector().select(verification)
            claim_only_ids = [
                candidate.ingredient_id
                for candidate in recommendations.candidates
                if candidate.basis is RecommendationBasis.CLAIM_ONLY
            ]
            product_result = await self._products.search(
                ProductSearchRequest(
                    filters=ProductSearchFilters(ingredient_ids=claim_only_ids),
                    limit=self.PRODUCT_SAMPLE_LIMIT,
                )
            )
            if product_result.status not in (LookupStatus.SUCCESS, LookupStatus.NO_RESULTS):
                raise RuntimeError(
                    f"Product smoke 검색 실패: status={product_result.status.value}, "
                    f"error={product_result.error_message}"
                )
            with_product = await self._claim_only_with_products(claim_only_ids)
            return TwoLayerDumpSmokeReport(
                database=self.DATABASE_NAME,
                embedding_model=self._claims.embedding_model.value,
                claim_count=len(claims.hits),
                low_confidence_claim_count=sum(
                    hit.confidence is ClaimConfidence.LOW for hit in claims.hits
                ),
                evidence_record_count=len(evidence.records),
                unreviewed_evidence_count=sum(
                    record.review_status is EvidenceReviewStatus.UNREVIEWED
                    for record in evidence.records
                ),
                claim_only_ingredient_count=len(claim_only_ids),
                claim_only_with_product_count=with_product,
                unique_product_sample_count=len(
                    {product.product_id for product in product_result.products}
                ),
            )
        finally:
            await self._database.dispose()

    async def _claim_only_with_products(self, ingredient_ids: list[str]) -> int:
        count = 0
        for ingredient_id in ingredient_ids:
            result = await self._products.search(
                ProductSearchRequest(
                    filters=ProductSearchFilters(ingredient_ids=[ingredient_id]),
                    limit=1,
                )
            )
            if result.status is LookupStatus.SUCCESS:
                count += 1
        return count

    def _create_database(self) -> Database:
        url = make_url(settings.database.url).set(database=self.DATABASE_NAME)
        return Database(
            DatabaseConfig(
                url=url.render_as_string(hide_password=False),
                model_modules=settings.database.model_modules,
            )
        )

    def _embedding_config(self) -> LocalEmbeddingConfig:
        embedding = settings.agent.embedding
        device = (
            LocalModelDevice(embedding.device.value)
            if embedding.device is not None
            else None
        )
        return LocalEmbeddingConfig(
            model=LocalEmbeddingModel.BGE_M3,
            device=device,
            batch_size=embedding.batch_size,
            cache_folder=embedding.cache_folder,
            local_files_only=embedding.local_files_only,
        )


class TwoLayerRagDumpSmokeCli:
    """smoke 결과를 JSON으로 출력하는 CLI 진입점."""

    def run(self) -> None:
        report = asyncio.run(TwoLayerRagDumpSmokeRunner().run())
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    TwoLayerRagDumpSmokeCli().run()
