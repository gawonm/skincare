"""실제 OpenAI 임베딩·생성 호출까지 포함한 end-to-end 검증. `pytest -m integration`으로만 실행한다.

로컬 DB에 이미 적재된 실 데이터(Evidence/IngredientKnowledgeFact/NIA)에 의존한다 -
`backend/services/rag_ingestion_service.py`로 한 번 이상 적재돼 있어야 통과한다.
"""

import pytest

from agent.rag.embedding.openai_embedder import OpenAiEmbedder
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.retrieval.hybrid_retriever import HybridRetriever
from agent.rag.retrieval.question_intent_classifier import QuestionIntent, QuestionIntentClassifier
from agent.rag.schemas import UnverifiableReason
from backend.repositories.rag_chunk_repository import RagChunkRepository
from core.config import settings


async def _ask(session, question: str, top_k: int = 5):
    embedder = OpenAiEmbedder(
        api_key=settings.openai.api_key, model=settings.openai.embedding_model
    )
    generator = AnswerGenerator(api_key=settings.openai.api_key, model=settings.openai.chat_model)
    intents = tuple(QuestionIntentClassifier().classify(question))
    is_combination_question = QuestionIntent.COMBINATION in intents

    query_vector = embedder.embed_query(question)
    repo = RagChunkRepository(session)
    vector_results = await repo.search_by_vector(
        list(query_vector), top_k=top_k, ingredient_id=None
    )
    bm25_results = await repo.search_by_bm25(question, top_k=top_k, ingredient_id=None)
    retrieved = HybridRetriever().fuse(vector_results, bm25_results, top_k=top_k)
    return generator.generate(
        question, retrieved, intents=intents, is_combination_question=is_combination_question
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_regulation_question_with_official_evidence_succeeds(session):
    result = await _ask(
        session, "p-하이드록시벤조익애씨드(파라벤류) 국내 배합 한도가 어떻게 되나요?"
    )

    assert result.has_verifiable_evidence
    assert result.answer
    assert result.sources
    assert result.sources[0].confidence_tier.value == "official_regulatory"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_usage_frequency_question_has_no_structured_axis_so_insufficient(session):
    """구조화 소스에 사용주기 전용 필드가 없다 - 성분이 맞아도 근거 부족이어야 한다."""
    result = await _ask(session, "1,2-Hexanediol 이 성분은 하루에 몇 번 사용해야 하나요?")

    assert not result.has_verifiable_evidence
    assert result.unverifiable_reason == UnverifiableReason.NOT_RELEVANT_TO_QUESTION


@pytest.mark.integration
@pytest.mark.asyncio
async def test_nonsense_question_returns_no_evidence_found(session):
    result = await _ask(session, "오늘 서울 날씨 어때요?")

    assert not result.has_verifiable_evidence


@pytest.mark.integration
@pytest.mark.asyncio
async def test_combination_question_without_relationship_evidence_is_insufficient(session):
    """개별 성분 근거는 둘 다 있어도, 조합 자체를 다루는 근거가 없으면 근거 부족이어야 한다.

    이 질문이 COMBINATION 하나만 감지되면 예전 버그로 축 필터에서 전부 걸러져
    NOT_RELEVANT_TO_QUESTION이 나왔었다(2026-09-10 수정) - 지금은 그 필터를 통과해서
    실제 조합 근거 검사(MISSING_COMBINATION_EVIDENCE)까지 도달해야 한다.
    """
    result = await _ask(session, "레티놀이랑 살리실릭애씨드 같이 써도 되나요?", top_k=8)

    assert not result.has_verifiable_evidence
    assert result.unverifiable_reason == UnverifiableReason.MISSING_COMBINATION_EVIDENCE
