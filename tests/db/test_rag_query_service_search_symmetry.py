"""`RagQueryService._search`가 성분 나열 순서와 무관하게 같은 청크·점수를 내는지 검증.

OpenAI 호출 없음 - 고정 벡터를 돌려주는 가짜 임베더를 써서 임베딩 API의 자체 비결정성을
제거하고, 오직 "성분 순서를 바꿨을 때 병합 로직이 같은 결과를 내는가"만 본다. 최종 판정
(has_verifiable_evidence)만 같은 걸로는 부족하다 - 그 판정을 만든 검색 결과 자체(청크 ID와
점수)가 동일해야 검색 단계의 순서 편향이 없다고 확신할 수 있다(2026-09-10 지적 반영).
"""

import pytest
from sqlalchemy import select

from agent.rag.schemas import RagChunkDraft
from backend.services.rag_query_service import RagQueryService
from models.ingredient import IngredientMaster


class _FixedVectorEmbedder:
    """`embed_query`가 항상 같은 벡터를 돌려준다 - 임베딩 API 비결정성을 검색 단계 검증에서 뺀다."""

    def embed_query(self, text: str) -> tuple[float, ...]:
        return tuple([0.001] * 1536)

    def embed(self, drafts: list[RagChunkDraft]):
        raise NotImplementedError("이 테스트는 조회만 한다 - 적재는 쓰지 않는다")


async def _ingredient_id(session, standard_name_ko: str):
    result = await session.execute(
        select(IngredientMaster.id).where(IngredientMaster.standard_name_ko == standard_name_ko)
    )
    ingredient_id = result.scalar_one_or_none()
    assert ingredient_id is not None, f"'{standard_name_ko}' 성분이 IngredientMaster에 없음"
    return ingredient_id


@pytest.mark.asyncio
async def test_search_result_chunk_ids_and_scores_are_identical_regardless_of_ingredient_order(
    session,
):
    retinol_id = await _ingredient_id(session, "레티놀")
    niacinamide_id = await _ingredient_id(session, "나이아신아마이드")

    service = RagQueryService(
        session,
        embedder=_FixedVectorEmbedder(),
        generator=None,  # type: ignore[arg-type] - _search는 generator를 안 쓴다
        mention_resolver=None,  # type: ignore[arg-type] - _search는 mention_resolver도 안 쓴다
    )

    question = "레티놀이랑 나이아신아마이드 같이 써도 되나요?"
    forward = await service._search(question, [retinol_id, niacinamide_id])
    backward = await service._search(question, [niacinamide_id, retinol_id])

    forward_by_id = {chunk.chunk_id: chunk.fused_score for chunk in forward}
    backward_by_id = {chunk.chunk_id: chunk.fused_score for chunk in backward}

    # 같은 청크 집합이어야 한다 (순서만 바뀌었을 뿐 검색 대상 성분은 동일하므로).
    assert set(forward_by_id) == set(backward_by_id)
    # 청크마다 점수도 완전히 같아야 한다 - 순서가 점수 계산에 영향을 주면 안 된다.
    assert forward_by_id == backward_by_id
    # 최종 리스트 순서(점수 내림차순 정렬)도 동일해야 한다.
    assert [chunk.chunk_id for chunk in forward] == [chunk.chunk_id for chunk in backward]
