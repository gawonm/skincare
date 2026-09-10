"""DB 어댑터 대신 계약 대역을 주입해 실제 청킹·검색 통합·인용 검증을 연결한다."""

from enum import StrEnum
from typing import ClassVar

import pytest

from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.pipeline import (
    EvidenceApplicabilityEvaluator,
    EvidencePipeline,
    RagIngestionPipeline,
)
from agent.rag.ports import ClaimGenerator, HybridSearchBackend, TextEmbedder
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.schemas import (
    ClaimGenerationRequest,
    EmbeddedChunk,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingVector,
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceScope,
    EvidenceSearchRequest,
    GeneratedClaim,
    GeneratedClaims,
    HybridSearchRequest,
    HybridSearchResult,
    LookupStatus,
    QuestionIntent,
    RagConfidenceTier,
    RagDocument,
    RagDocumentField,
    RagRetrievalPolicy,
    RetrievedChunk,
    UnverifiableReason,
)


class GenerationMode(StrEnum):
    VALID = "valid"
    OMIT_CONDITION = "omit_condition"
    UNKNOWN_CITATION = "unknown_citation"


class ContractEmbedder(TextEmbedder):
    MODEL: ClassVar[str] = "contract-test-model"

    def __init__(self, drop_last: bool = False) -> None:
        self.drop_last = drop_last
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self.requests.append(request)
        vectors = [EmbeddingVector(values=[1.0, 0.0]) for _ in request.texts]
        return EmbeddingResult(
            model=self.MODEL, vectors=vectors[:-1] if self.drop_last else vectors
        )


class ContractSearchBackend(HybridSearchBackend):
    def __init__(
        self, chunks: list[EmbeddedChunk], status: LookupStatus = LookupStatus.SUCCESS
    ) -> None:
        self.chunks = chunks
        self.status = status
        self.requests: list[HybridSearchRequest] = []

    async def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        self.requests.append(request)
        if self.status is not LookupStatus.SUCCESS:
            return HybridSearchResult(
                status=self.status, error_message="계약 테스트: 미지원 검색 조건"
            )
        hits = [
            RetrievedChunk(chunk=chunk.draft, vector_similarity=0.8, bm25_relevance=2.0)
            for chunk in self.chunks
            if not request.request.target_ids
            or set(request.request.target_ids).intersection(chunk.draft.evidence.target_ids)
        ]
        return HybridSearchResult(
            status=LookupStatus.SUCCESS if hits else LookupStatus.NO_RESULTS,
            vector_results=hits,
            bm25_results=list(reversed(hits)),
        )


class ContractClaimGenerator(ClaimGenerator):
    def __init__(self, mode: GenerationMode = GenerationMode.VALID) -> None:
        self.mode = mode
        self.requests: list[ClaimGenerationRequest] = []

    async def generate(self, request: ClaimGenerationRequest) -> GeneratedClaims:
        self.requests.append(request)
        return GeneratedClaims(
            claims=[
                GeneratedClaim(
                    sentence=record.text
                    if self.mode is not GenerationMode.OMIT_CONDITION
                    else "조건 누락",
                    evidence_ids=[record.evidence_id]
                    if self.mode is not GenerationMode.UNKNOWN_CITATION
                    else ["missing"],
                )
                for record in request.records
            ]
        )


class RagContractFixture:
    TARGET_A: ClassVar[str] = "test:ingredient-a"
    TARGET_B: ClassVar[str] = "test:ingredient-b"

    def document(self, target: str) -> RagDocument:
        return RagDocument(
            evidence=EvidenceRecord(
                evidence_id=f"test:evidence:{target}",
                source_id="contract:source",
                source_title="검사 전용 합성 자료",
                document_version="test-v1",
                locator="test:row-1",
                text="한국에서 0.4% 이하 조건을 보존하는 검사 전용 문장입니다.",
                target_ids=[target],
                scope=EvidenceScope.INGREDIENT,
                conditions=EvidenceConditions(concentration="0.4% 이하", jurisdiction="한국"),
                review_status=EvidenceReviewStatus.VERIFIED,
                is_demo=False,
            ),
            fields=[
                RagDocumentField(
                    field_id="efficacy",
                    content="검사 전용 효능 필드",
                    intents=[QuestionIntent.EFFICACY, QuestionIntent.PRECAUTION],
                )
            ],
            confidence_tier=RagConfidenceTier.STRUCTURED_KNOWLEDGE,
        )

    def pipeline(self, backend: HybridSearchBackend, generator: ClaimGenerator) -> EvidencePipeline:
        return EvidencePipeline(
            retriever=HybridEvidenceRetriever(
                backend=backend,
                embedder=ContractEmbedder(),
                policy=RagRetrievalPolicy(free_text_min_vector_similarity=0.5),
            ),
            evaluator=EvidenceApplicabilityEvaluator(),
            generator=AnswerGenerator(generator),
        )


class TestRagContract:
    async def test_ingestion_search_generation_preserves_sources_conditions_and_scores(
        self,
    ) -> None:
        fixture = RagContractFixture()
        embedder = ContractEmbedder()
        document = fixture.document(fixture.TARGET_A)
        chunks = await RagIngestionPipeline(FieldChunker(), embedder).run([document])
        assert chunks[0].draft.evidence == document.evidence
        assert chunks[0].embedding_model == embedder.MODEL
        backend = ContractSearchBackend(chunks)
        generator = ContractClaimGenerator()
        result = await fixture.pipeline(backend, generator).run(
            EvidenceSearchRequest(
                query="성분 효능",
                target_ids=[fixture.TARGET_A],
                known_conditions=document.evidence.conditions,
            )
        )
        assert result.generated is not None
        answer = result.generated.per_target[0].result
        assert answer.has_verifiable_evidence
        assert answer.claims[0].sources == [document.evidence]
        assert "0.4% 이하" in answer.answer
        assert result.search.chunks[0].vector_similarity == 0.8
        assert result.search.chunks[0].bm25_relevance == 2.0
        assert result.search.chunks[0].fused_score > 0
        assert backend.requests[0].embedding_model == embedder.MODEL

    async def test_embedding_cardinality_failure_and_duplicate_fields_are_explicit(self) -> None:
        fixture = RagContractFixture()
        document = fixture.document(fixture.TARGET_A)
        with pytest.raises(ValueError, match="청크와 임베딩 수"):
            await RagIngestionPipeline(FieldChunker(), ContractEmbedder(drop_last=True)).run(
                [document]
            )
        document.fields.append(document.fields[0].model_copy())
        with pytest.raises(ValueError, match="field_id가 중복"):
            FieldChunker().chunk(document)

    async def test_target_order_cannot_change_scores_or_prove_combination(self) -> None:
        fixture = RagContractFixture()
        chunks = await RagIngestionPipeline(FieldChunker(), ContractEmbedder()).run(
            [
                fixture.document(fixture.TARGET_A),
                fixture.document(fixture.TARGET_B),
            ]
        )
        generator = ContractClaimGenerator()
        pipeline = fixture.pipeline(ContractSearchBackend(chunks), generator)
        request = EvidenceSearchRequest(
            query="두 성분 같이 써도 되는지 효능과 주의사항",
            target_ids=[fixture.TARGET_A, fixture.TARGET_B],
            combination_target_ids=[fixture.TARGET_A, fixture.TARGET_B],
        )
        result = await pipeline.run(request)
        reversed_result = await pipeline.run(
            request.model_copy(update={"target_ids": list(reversed(request.target_ids))})
        )
        assert result.search.chunks == reversed_result.search.chunks
        assert result.generated is not None and result.generated.combination is not None
        assert (
            result.generated.combination.unverifiable_reason
            is UnverifiableReason.MISSING_COMBINATION_EVIDENCE
        )
        assert all(
            not call.is_combination and "같이" not in call.question for call in generator.requests
        )

    async def test_invalid_claims_are_not_promoted_to_verified_answers(self) -> None:
        fixture = RagContractFixture()
        chunks = await RagIngestionPipeline(FieldChunker(), ContractEmbedder()).run(
            [fixture.document(fixture.TARGET_A)]
        )
        for mode in (GenerationMode.OMIT_CONDITION, GenerationMode.UNKNOWN_CITATION):
            result = await fixture.pipeline(
                ContractSearchBackend(chunks), ContractClaimGenerator(mode)
            ).run(EvidenceSearchRequest(query="효능", target_ids=[fixture.TARGET_A]))
            assert result.generated is not None
            assert (
                result.generated.per_target[0].result.unverifiable_reason
                is UnverifiableReason.CITATION_VALIDATION_FAILED
            )

    async def test_unsupported_search_never_calls_generator(self) -> None:
        fixture = RagContractFixture()
        generator = ContractClaimGenerator()
        result = await fixture.pipeline(
            ContractSearchBackend([], LookupStatus.UNSUPPORTED), generator
        ).run(EvidenceSearchRequest(query="효능", target_ids=[fixture.TARGET_A]))
        assert result.search.status is LookupStatus.UNSUPPORTED
        assert result.generated is None
        assert not generator.requests

    async def test_unreviewed_source_is_not_promoted_by_source_tier(self) -> None:
        fixture = RagContractFixture()
        document = fixture.document(fixture.TARGET_A)
        document.evidence.review_status = EvidenceReviewStatus.UNREVIEWED
        chunks = await RagIngestionPipeline(FieldChunker(), ContractEmbedder()).run([document])
        generator = ContractClaimGenerator()
        result = await fixture.pipeline(ContractSearchBackend(chunks), generator).run(
            EvidenceSearchRequest(query="효능", target_ids=[fixture.TARGET_A])
        )
        assert result.generated is not None
        assert (
            result.generated.per_target[0].result.unverifiable_reason
            is UnverifiableReason.UNREVIEWED_EVIDENCE
        )
        assert not generator.requests
