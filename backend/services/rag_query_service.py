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
    RetrievedChunk,
    UnverifiableReason,
)
from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from backend.repositories.rag_chunk_repository import RagChunkRepository

# 검색 결과 개수. HybridRetriever.fuse의 top_k와 동일한 의미로, 벡터/BM25 각각 이만큼 뽑아
# RRF로 합친다.
_DEFAULT_TOP_K = 8

# 조합 질문에서 개별 성분 결과를 낼 때 쓰는 질문 텍스트. 원본 질문("A랑 B 같이 써도
# 되나요?")을 그대로 쓰면 LLM이 그 문맥을 보고 개별 답변에서도 병용 가능성을 암묵적으로
# 언급할 위험이 있다(2026-09-10 지적 반영) - 병용 판정은 반드시 combination 결과에서만
# 나와야 하므로, 개별 결과는 성분 하나만 두고 묻는 중립적인 질문으로 완전히 바꾼다.
_INDIVIDUAL_QUESTION_TEMPLATE = "{ingredient_name}의 효능과 주의사항이 무엇인가요?"

# 자유 텍스트(성분 미특정) 질문의 관련성 판정 임계값. 성분 필터가 없으면 RRF 순위만으로는
# "질문과 실제로 관련 있는 결과"를 "그나마 제일 가까운 결과"와 구분하지 못한다 - 무관한
# 질문도 상대적 1등은 나온다. 그래서 최상위 결과의 코사인 유사도 원점수가 이 값을 못
# 넘기면, 신뢰도 티어가 높은 자료가 검색됐더라도 답변을 보류한다.
#
# 값을 정한 방법(2026-09-10): 튜닝셋(관련 질문 3개, 무관 질문 3개, 이 임계값을 정하는
# 데만 씀)에서 관련 질문의 top_vector_similarity는 0.519~0.725, 무관 질문은 0.267~0.407로
# 뚜렷이 갈렸다. 그 중간값 0.45를 임계값으로 정하고, 튜닝에 안 쓴 별도 검증셋(관련 2개,
# 무관 2개)으로 확인해 4/4 정확히 갈렸다. 두 세트를 분리한 이유: 같은 사례로 기준을
# 정하고 그걸로 통과 여부까지 확인하면 검증력이 없다.
_FREE_TEXT_MIN_VECTOR_SIMILARITY = 0.45


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
            return RagQueryResult(free_text=await self._answer_free_text(question, intents))

        per_ingredient: list[PerIngredientResult] = []
        resolved_ids: list[UUID] = []
        for mention in mentions:
            per_ingredient.append(
                await self._resolve_one(question, mention, intents, is_combination_intent)
            )
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
        is_combination_intent: bool,
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
        # 조합 질문이면 원본 질문("A랑 B 같이 써도 되나요?") 대신 중립적인 단일 성분
        # 질문으로 바꿔서 검색·생성한다 - 개별 답변에 병용 문맥이 새어 들어가지 않게 한다.
        individual_question = (
            _INDIVIDUAL_QUESTION_TEMPLATE.format(ingredient_name=mention.matched_text)
            if is_combination_intent
            else question
        )
        result = await self._search_and_generate(
            individual_question,
            ingredient_ids=[mention.ingredient_id],
            intents=intents,
            is_combination_question=False,
        )
        return PerIngredientResult(
            matched_text=mention.matched_text, ingredient_id=mention.ingredient_id, result=result
        )

    async def _answer_free_text(
        self, question: str, intents: tuple[QuestionIntent, ...]
    ) -> IngredientVerificationResult:
        """성분이 특정 안 된 질문. 성분 필터가 없어 관련성을 원점수로 직접 확인해야 한다.

        신뢰도 높은 근거가 검색됐더라도, 그게 질문과 실제로 관련 있다는 뜻은 아니다 -
        "무관한 질문에 신뢰도 높은 자료가 검색되더라도 답변을 보류한다"가 핵심 기준이다
        (2026-09-10). 근거를 아예 안 찾은 경우와 구분하기 위해 검색 자체는 하되, LLM
        호출(비용 발생) 전에 관련성부터 확인해서 걸러진 경우는 생성 단계로 안 보낸다.
        """
        retrieved = await self._search(question, ingredient_ids=None)
        if not self._is_relevant(retrieved):
            return IngredientVerificationResult(
                has_verifiable_evidence=False,
                unverifiable_reason=UnverifiableReason.NOT_RELEVANT_TO_QUESTION,
            )
        return self._generator.generate(
            question, retrieved, intents=intents, is_combination_question=False
        )

    def _is_relevant(self, retrieved: list[RetrievedChunk]) -> bool:
        return any(
            (chunk.vector_similarity or 0.0) >= _FREE_TEXT_MIN_VECTOR_SIMILARITY
            for chunk in retrieved
        )

    async def _search_and_generate(
        self,
        question: str,
        ingredient_ids: list[UUID] | None,
        intents: tuple[QuestionIntent, ...],
        is_combination_question: bool,
    ) -> IngredientVerificationResult:
        retrieved = await self._search(question, ingredient_ids)
        return self._generator.generate(
            question, retrieved, intents=intents, is_combination_question=is_combination_question
        )

    async def _search(
        self, question: str, ingredient_ids: list[UUID] | None
    ) -> list[RetrievedChunk]:
        query_vector = list(self._embedder.embed_query(question))

        if not ingredient_ids or len(ingredient_ids) == 1:
            ingredient_id = ingredient_ids[0] if ingredient_ids else None
            vector_results = await self._repo.search_by_vector(
                query_vector, self._top_k, ingredient_id
            )
            bm25_results = await self._repo.search_by_bm25(question, self._top_k, ingredient_id)
            return self._retriever.fuse(vector_results, bm25_results, self._top_k)

        # 복수 성분(조합 질문): 성분마다 따로 검색해서 각자 fuse부터 끝낸다. RRF 점수는
        # 그 성분 내부 순위(1..top_k)만으로 계산되므로 성분별로 독립적으로 비교 가능한
        # 척도다 - 이렇게 하면 "성분을 나열한 순서"가 최종 순위에 영향을 주지 않는다.
        # (예전엔 성분별 원시 결과를 이어붙인 뒤 통째로 fuse해서, 리스트 뒤쪽 성분의
        # 실제 1등 결과가 앞쪽 성분 결과들 뒤로 밀려 순위가 밀리는 편향이 있었다 -
        # 2026-09-10 지적으로 발견.)
        merged: list[RetrievedChunk] = []
        for ingredient_id in ingredient_ids:
            vector_results = await self._repo.search_by_vector(
                query_vector, self._top_k, ingredient_id
            )
            bm25_results = await self._repo.search_by_bm25(question, self._top_k, ingredient_id)
            merged.extend(self._retriever.fuse(vector_results, bm25_results, self._top_k))

        # 점수가 완전히 같은 동점 청크가 나올 수 있다(예: 두 성분의 근거 내용이 겹칠
        # 때). 점수만으로 정렬하면 동점 처리 순서가 리스트에 쌓인 순서(=성분 나열
        # 순서)에 좌우돼 결과가 미묘하게 달라질 수 있어, chunk_id를 2차 정렬 키로 둬서
        # 동점이어도 항상 같은 순서가 나오게 한다(2026-09-10 실제 테스트로 확인).
        merged.sort(key=lambda chunk: (-(chunk.fused_score or 0.0), str(chunk.chunk_id)))
        return merged[: self._top_k]
