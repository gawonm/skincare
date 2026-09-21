"""RAG 파이프라인이 외부 검색 구현에 요구하는 계약."""

from abc import ABC, abstractmethod

from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimExtractionResult,
)
from agent.rag.case_schemas import (
    CaseRerankRequest,
    CaseRerankResult,
    CaseSearchRequest,
    CaseSearchResult,
)
from agent.rag.claim_schemas import ClaimSearchRequest, ClaimSearchResult
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    EvidenceStatementGenerationRequest,
    GeneratedEvidenceStatements,
    HybridSearchRequest,
    HybridSearchResult,
    LocalEmbeddingModel,
    RerankRequest,
    RerankResult,
)


class CaseRetriever(ABC):
    @abstractmethod
    async def search(self, request: CaseSearchRequest) -> CaseSearchResult:
        raise NotImplementedError


class CaseReranker(ABC):
    @abstractmethod
    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        raise NotImplementedError


class CaseClaimExtractor(ABC):
    @abstractmethod
    async def extract(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionResult:
        raise NotImplementedError


class ClaimRetriever(ABC):
    """NIA Claim 전용 검색 포트. Evidence 검색 결과를 반환하지 않는다."""

    @property
    @abstractmethod
    def embedding_model(self) -> LocalEmbeddingModel:
        """Claim 색인과 질의에 사용한 임베딩 모델을 반환한다."""
        raise NotImplementedError

    @abstractmethod
    async def search(self, request: ClaimSearchRequest) -> ClaimSearchResult:
        raise NotImplementedError


class EvidenceRetriever(ABC):
    @abstractmethod
    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        raise NotImplementedError


class TextEmbedder(ABC):
    @abstractmethod
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError


class HybridSearchBackend(ABC):
    """주입자가 DB·검색엔진을 선택한다. 점수는 원점수 내림차순으로 반환한다.

    target_ids는 OR 필터이며, combination_target_ids가 있으면 그 관계 근거도 검색한다.
    지원할 수 없는 필터는 무시하지 말고 UNSUPPORTED로 반환한다.
    """

    @abstractmethod
    async def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        raise NotImplementedError


class EvidenceReranker(ABC):
    @abstractmethod
    async def rerank(self, request: RerankRequest) -> RerankResult:
        raise NotImplementedError


class EvidenceStatementGenerator(ABC):
    @abstractmethod
    async def generate(
        self,
        request: EvidenceStatementGenerationRequest,
    ) -> GeneratedEvidenceStatements:
        raise NotImplementedError
