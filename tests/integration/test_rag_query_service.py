"""`RagQueryService` 조립 전체를 실제 데이터·실제 OpenAI 호출로 검증한다."""

import pytest

from agent.rag.embedding.openai_embedder import OpenAiEmbedder
from agent.rag.generation.answer_generator import AnswerGenerator
from backend.services.rag_query_service import RagQueryService
from core.config import settings


async def _service(session) -> RagQueryService:
    embedder = OpenAiEmbedder(
        api_key=settings.openai.api_key, model=settings.openai.embedding_model
    )
    generator = AnswerGenerator(api_key=settings.openai.api_key, model=settings.openai.chat_model)
    return await RagQueryService.create(session, embedder, generator)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_ingredient_question_resolves_and_answers(session):
    service = await _service(session)
    result = await service.answer("나이아신아마이드 효능이 뭐예요?")

    assert result.free_text is None
    assert len(result.per_ingredient) == 1
    assert result.per_ingredient[0].matched_text == "나이아신아마이드"
    assert result.per_ingredient[0].result.has_verifiable_evidence


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_ingredient_question_keeps_individual_and_combination_separate(session):
    """조합 질문에서 개별 성분 근거와 조합 근거가 섞이면 안 된다.

    두 성분 모두 개별 효능 근거는 있지만(따로 물으면 True), "같이 써도 되나요"는 조합
    자체를 다루는 근거가 없어 개별 결과와 무관하게 False여야 한다.
    """
    service = await _service(session)
    result = await service.answer("레티놀이랑 나이아신아마이드 같이 써도 되나요?")

    assert len(result.per_ingredient) == 2
    assert all(pi.result.has_verifiable_evidence for pi in result.per_ingredient)
    assert result.combination is not None
    assert not result.combination.has_verifiable_evidence


@pytest.mark.integration
@pytest.mark.asyncio
async def test_free_text_question_without_ingredient_mention(session):
    service = await _service(session)
    result = await service.answer("오늘 날씨 어때요?")

    assert result.free_text is not None
    assert result.per_ingredient == ()
    assert result.combination is None
