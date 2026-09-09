"""각 단계를 순서대로 조립해 하나의 흐름으로 실행한다.

백엔드는 개별 단계를 직접 호출하지 않고 이 파이프라인만 호출한다.
단계 구현이 바뀌어도 백엔드 코드는 그대로 둘 수 있다.

`agent`는 세션도 리포지토리도 직접 만들지 않는다는 규칙 때문에, 실제 DB 조회·검색 쿼리
(`backend/repositories/rag_chunk_repository.py`)는 이 파이프라인 밖(`backend/services/`)에서
실행되고 이미 조회된 결과만 여기로 들어온다. 그래서 이 파일은 두 파이프라인으로 나뉜다.

- `RagIngestionPipeline`: 이미 로더가 만든 `RagDocument` 목록 -> 청킹 -> 임베딩.
  저장(`RagChunkRepository.save_many`)은 `backend/services/`가 한다.
- `RagAnswerPipeline`: 이미 리포지토리가 실행한 벡터/BM25 검색 결과 -> 병합(RRF) -> 답변 생성.
  질문 임베딩과 검색 실행 자체는 `backend/services/`가 순서대로 호출한다(질문을 벡터로
  바꿔야 검색을 실행할 수 있어, 이 파이프라인 하나로 감쌀 수 없는 순환 의존이 생기기 때문).
"""

from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.embedding.openai_embedder import OpenAiEmbedder
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.retrieval.hybrid_retriever import HybridRetriever
from agent.rag.schemas import EmbeddedChunk, IngredientVerificationResult, RagDocument
from models.rag_chunk import RagChunk


class RagIngestionPipeline:
    """`RagDocument` 목록을 청킹·임베딩해 저장 직전 상태(`EmbeddedChunk`)로 만든다."""

    def __init__(self, chunker: FieldChunker, embedder: OpenAiEmbedder) -> None:
        self._chunker = chunker
        self._embedder = embedder

    def run(self, documents: list[RagDocument]) -> list[EmbeddedChunk]:
        drafts = [draft for document in documents for draft in self._chunker.chunk(document)]
        return self._embedder.embed(drafts)


class RagAnswerPipeline:
    """검색 결과를 병합하고 답변을 생성한다."""

    def __init__(self, retriever: HybridRetriever, generator: AnswerGenerator) -> None:
        self._retriever = retriever
        self._generator = generator

    def run(
        self,
        question: str,
        vector_results: list[RagChunk],
        bm25_results: list[RagChunk],
        top_k: int,
    ) -> IngredientVerificationResult:
        retrieved = self._retriever.fuse(vector_results, bm25_results, top_k)
        return self._generator.generate(question, retrieved)
