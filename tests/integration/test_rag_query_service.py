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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_combination_ingredient_order_does_not_change_judgement(session):
    """ "A와 B"와 "B와 A"는 같은 근거를 동등하게 취급해야 한다(2026-09-10 지적, 수정).

    예전엔 성분별 검색 결과를 이어붙인 뒤 통째로 RRF를 매겨서, 나중에 언급된 성분의
    실제 1등 근거가 먼저 언급된 성분의 결과들 뒤로 밀리는 순서 편향이 있었다.
    """
    service = await _service(session)

    forward = await service.answer("레티놀이랑 나이아신아마이드 같이 써도 되나요?")
    backward = await service.answer("나이아신아마이드랑 레티놀 같이 써도 되나요?")

    assert forward.combination is not None
    assert backward.combination is not None
    assert (
        forward.combination.has_verifiable_evidence == backward.combination.has_verifiable_evidence
    )
    assert forward.combination.unverifiable_reason == backward.combination.unverifiable_reason

    forward_by_ingredient = {
        pi.matched_text: pi.result.has_verifiable_evidence for pi in forward.per_ingredient
    }
    backward_by_ingredient = {
        pi.matched_text: pi.result.has_verifiable_evidence for pi in backward.per_ingredient
    }
    assert forward_by_ingredient == backward_by_ingredient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_individual_answers_in_combination_question_do_not_mention_the_other_ingredient(
    session,
):
    """조합 질문의 개별 결과는 그 성분 설명만 담당하고 병용 여부는 언급하면 안 된다.

    개별 답변에 원본 질문("A랑 B 같이 써도 되나요")을 그대로 넘기면 LLM이 그 문맥을 보고
    병용 가능성을 암묵적으로 언급할 위험이 있었다(2026-09-10 지적, 중립 질문으로 분리해 수정).
    """
    service = await _service(session)
    result = await service.answer("레티놀이랑 나이아신아마이드 같이 써도 되나요?")

    by_ingredient = {pi.matched_text: pi.result for pi in result.per_ingredient}
    retinol_answer = by_ingredient["레티놀"].answer or ""
    niacinamide_answer = by_ingredient["나이아신아마이드"].answer or ""

    # 서로 다른 성분명이 상대방 답변에 섞여 들어오면 안 된다 - "레티놀" 답변에
    # "나이아신아마이드"가, 그 반대가 언급되면 병용 문맥이 새어 들어간 것이다.
    assert "나이아신아마이드" not in retinol_answer
    assert "레티놀" not in niacinamide_answer
