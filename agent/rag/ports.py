"""RAG 파이프라인이 외부 검색 구현에 요구하는 계약."""

from abc import ABC, abstractmethod

from agent.rag.schemas import EvidenceSearchRequest, EvidenceSearchResult


class EvidenceRetriever(ABC):
    @abstractmethod
    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        raise NotImplementedError
