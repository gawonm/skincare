"""RAG 파이프라인이 외부 검색 구현에 요구하는 계약."""

from abc import ABC, abstractmethod

from agent.rag.schemas import (
    ClaimGenerationRequest,
    EmbeddingRequest,
    EmbeddingResult,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    GeneratedClaims,
    HybridSearchRequest,
    HybridSearchResult,
)


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


class ClaimGenerator(ABC):
    @abstractmethod
    async def generate(self, request: ClaimGenerationRequest) -> GeneratedClaims:
        raise NotImplementedError
