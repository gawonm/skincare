"""질문 하나를 받아 `RagQueryResult`를 만드는 조회 진입점.

지금까지 따로 검증된 부품들(`IngredientMentionResolver`, `QuestionIntentClassifier`,
`HybridRetriever`, `AnswerGenerator`)을 여기서 조립한다. `backend/services/`에 두는 이유는
`rag_ingestion_service.py`와 같다 - `agent`(검색·생성)와 `backend/repositories`(DB 쿼리)
양쪽이 필요한데 `scripts/`는 그 둘을 import할 수 없다.

성분이 특정된 질문은 그 성분으로 검색을 좁히고(다른 성분 근거로 대체하지 않는다), 모호한
언급은 검색을 아예 안 하고 "명확화 필요"로 반환한다. 복수 성분 질문은 개별 성분 판정과
조합 판정을 분리해서 담는다 - "성분 A 근거 + 성분 B 근거"를 "같이 써도 된다"로 합치지 않는다.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent.rag.embedding.openai_embedder import OpenAiEmbedder
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.retrieval.hybrid_retriever import HybridRetriever
from agent.rag.retrieval.ingredient_mention_resolver import (
    IngredientMentionResolution,
    IngredientMentionResolver,
)
from agent.rag.retrieval.question_intent_classifier import QuestionIntent, QuestionIntentClassifier
from agent.rag.schemas import (
    IngredientVerificationResult,
    PerIngredientResult,
    RagQueryResult,
    UnverifiableReason,
)
from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from backend.repositories.rag_chunk_repository import RagChunkRepository
from models.rag_chunk import RagChunk

# 검색 결과 개수. HybridRetriever.fuse의 top_k와 동일한 의미로, 벡터/BM25 각각 이만큼 뽑아
# RRF로 합친다.
_DEFAULT_TOP_K = 8


class RagQueryService:
    """질문 텍스트 하나를 `RagQueryResult`로 바꾼다. DB에 쓰지 않는다(조회 전용)."""

    def __init__(
        self,
        session: AsyncSession,
        embedder: OpenAiEmbedder,
        generator: AnswerGenerator,
        mention_resolver: IngredientMentionResolver,
        top_k: int = _DEFAULT_TOP_K,
    ) -> None:
        self._repo = RagChunkRepository(session)
        self._embedder = embedder
        self._generator = generator
        self._mention_resolver = mention_resolver
        self._intent_classifier = QuestionIntentClassifier()
        self._retriever = HybridRetriever()
        self._top_k = top_k

    @classmethod
    async def create(
        cls, session: AsyncSession, embedder: OpenAiEmbedder, generator: AnswerGenerator
    ) -> "RagQueryService":
        """`IngredientMaster` 후보를 조회해 `IngredientMentionResolver`를 만들어준다."""
        candidates = await IngredientMasterRepository(session).list_all_as_candidates()
        return cls(session, embedder, generator, IngredientMentionResolver(candidates))

    async def answer(self, question: str) -> RagQueryResult:
        intents = tuple(self._intent_classifier.classify(question))
        is_combination_intent = QuestionIntent.COMBINATION in intents
        mentions = self._mention_resolver.resolve(question)

        if not mentions:
            free_text_result = await self._search_and_generate(
                question, ingredient_ids=None, intents=intents, is_combination_question=False
            )
            return RagQueryResult(free_text=free_text_result)

        per_ingredient: list[PerIngredientResult] = []
        resolved_ids: list[UUID] = []
        for mention in mentions:
            per_ingredient.append(await self._resolve_one(question, mention, intents))
            if not mention.ambiguous and mention.ingredient_id is not None:
                resolved_ids.append(mention.ingredient_id)

        combination_result = None
        if is_combination_intent and len(resolved_ids) >= 2:
            combination_result = await self._search_and_generate(
                question, ingredient_ids=resolved_ids, intents=intents, is_combination_question=True
            )

        return RagQueryResult(per_ingredient=tuple(per_ingredient), combination=combination_result)

    async def _resolve_one(
        self,
        question: str,
        mention: IngredientMentionResolution,
        intents: tuple[QuestionIntent, ...],
    ) -> PerIngredientResult:
        if mention.ambiguous or mention.ingredient_id is None:
            return PerIngredientResult(
                matched_text=mention.matched_text,
                ingredient_id=None,
                result=IngredientVerificationResult(
                    has_verifiable_evidence=False,
                    unverifiable_reason=UnverifiableReason.AMBIGUOUS_INGREDIENT,
                ),
            )
        result = await self._search_and_generate(
            question,
            ingredient_ids=[mention.ingredient_id],
            intents=intents,
            is_combination_question=False,
        )
        return PerIngredientResult(
            matched_text=mention.matched_text, ingredient_id=mention.ingredient_id, result=result
        )

    async def _search_and_generate(
        self,
        question: str,
        ingredient_ids: list[UUID] | None,
        intents: tuple[QuestionIntent, ...],
        is_combination_question: bool,
    ) -> IngredientVerificationResult:
        query_vector = self._embedder.embed_query(question)
        vector_results = await self._search_by_vector(list(query_vector), ingredient_ids)
        bm25_results = await self._search_by_bm25(question, ingredient_ids)
        retrieved = self._retriever.fuse(vector_results, bm25_results, self._top_k)
        return self._generator.generate(
            question, retrieved, intents=intents, is_combination_question=is_combination_question
        )

    async def _search_by_vector(
        self, query_vector: list[float], ingredient_ids: list[UUID] | None
    ) -> list[RagChunk]:
        if not ingredient_ids:
            return await self._repo.search_by_vector(query_vector, self._top_k, ingredient_id=None)
        # 리포지토리는 성분 하나로만 좁히는 검색만 지원한다(단일 성분 질문이 압도적으로
        # 많아서 그게 기본 경로다) - 조합 질문처럼 여러 성분이 필요하면 성분마다 따로
        # 검색해 여기서 합친다.
        results: list[RagChunk] = []
        for ingredient_id in ingredient_ids:
            results.extend(
                await self._repo.search_by_vector(query_vector, self._top_k, ingredient_id)
            )
        return results

    async def _search_by_bm25(
        self, question: str, ingredient_ids: list[UUID] | None
    ) -> list[RagChunk]:
        if not ingredient_ids:
            return await self._repo.search_by_bm25(question, self._top_k, ingredient_id=None)
        results: list[RagChunk] = []
        for ingredient_id in ingredient_ids:
            results.extend(await self._repo.search_by_bm25(question, self._top_k, ingredient_id))
        return results
