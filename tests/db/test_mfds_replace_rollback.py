"""`RagIngestionService.replace_mfds_evidence_and_reindex`의 롤백 안전성. OpenAI 호출 없음.

가짜 임베더로 두 실패 지점을 각각 검증한다(2026-09-10 요청 반영 - 임베딩 실패 하나만으로는
트랜잭션 롤백 자체는 검증되지 않는다):

1. 준비 단계 실패: 임베딩 자체가 실패 - DB 쓰기가 시작도 안 됐으니 옛 데이터가 그대로 남는다.
2. DB 쓰기 단계 실패: 임베딩은 성공했지만(차원이 잘못된 벡터를 일부러 반환) DB INSERT가
   제약 위반으로 실패 - 이미 실행된 옛 Evidence 삭제까지 포함해 트랜잭션 전체가 롤백돼야
   한다.

실제 MFDS API를 호출하지 않는다 - `MfdsRestrictedIngredientItem`을 직접 만들어 넘긴다.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from agent.rag.schemas import EmbeddedChunk, RagChunkDraft
from backend.repositories.rag_chunk_repository import RagChunkInsert, RagChunkRepository
from backend.services.rag_ingestion_service import RagIngestionService
from models.evidence import Evidence, EvidenceSourceType, EvidenceTopic
from models.ingredient import IngredientMaster
from models.rag_chunk import RagChunk, RagChunkField, RagConfidenceTier, RagSourceTable
from scripts.evidence_schemas import MfdsRestrictedIngredientItem
from scripts.ingredient_name_matcher import IngredientNameMatcher
from scripts.ingredient_name_normalizer import IngredientNameNormalizer
from scripts.ingredient_schemas import IngredientCandidate


class _FailingEmbedder:
    """`embed()`가 항상 실패한다 - 준비 단계 실패를 흉내낸다."""

    def embed(self, drafts: list[RagChunkDraft]) -> list[EmbeddedChunk]:
        raise RuntimeError("임베딩 API 실패를 흉내낸다")


class _WrongDimensionEmbedder:
    """`embed()`는 성공하지만 차원이 잘못된 벡터를 준다 - DB INSERT 단계 실패를 흉내낸다.

    pgvector 컬럼은 1536차원으로 고정돼 있어서(EMBEDDING_DIMENSION), 다른 차원을 넣으면
    DB가 제약 위반으로 거부한다 - 목을 새로 만들지 않고 실제 DB 제약을 그대로 이용한다.
    """

    def embed(self, drafts: list[RagChunkDraft]) -> list[EmbeddedChunk]:
        return [
            EmbeddedChunk(draft=draft, vector=tuple([0.0] * 3), embedding_model="fake")
            for draft in drafts
        ]


async def _seed_existing_mfds_evidence(session, ingredient_id):
    evidence = Evidence(
        id=uuid4(),
        ingredient_id=ingredient_id,
        topic=EvidenceTopic.COSMETIC_USE_RESTRICTION,
        claim="한국 배합 규제: 한도(기존 데이터)",
        conditions="0.5% 이하",
        jurisdiction="한국",
        source_type=EvidenceSourceType.MFDS_RESTRICTED_INGREDIENT,
        source_title="식품의약품안전처 화장품 사용제한 원료정보",
        source_url="https://www.data.go.kr/data/15111772/openapi.do",
    )
    session.add(evidence)
    await session.flush()

    repo = RagChunkRepository(session)
    await repo.save_many(
        [
            RagChunkInsert(
                ingredient_id=ingredient_id,
                source_table=RagSourceTable.EVIDENCE,
                evidence_id=evidence.id,
                ingredient_knowledge_fact_id=None,
                nia_record_id=None,
                chunk_field=RagChunkField.EVIDENCE_CLAIM,
                chunk_index=0,
                content=evidence.claim,
                embedding=tuple([0.0] * 1536),
                embedding_model="fake-seed",
                confidence_tier=RagConfidenceTier.OFFICIAL_REGULATORY,
                cites_cir=False,
                source_title=evidence.source_title,
                source_url=evidence.source_url,
                citation_refs=(),
            )
        ]
    )
    return evidence


async def _mfds_evidence_count(session) -> int:
    result = await session.execute(
        select(Evidence).where(
            Evidence.source_type == EvidenceSourceType.MFDS_RESTRICTED_INGREDIENT
        )
    )
    return len(result.scalars().all())


async def _rag_chunk_count_for_evidence(session, evidence_id) -> int:
    result = await session.execute(select(RagChunk).where(RagChunk.evidence_id == evidence_id))
    return len(result.scalars().all())


async def _one_ingredient(session) -> IngredientMaster:
    result = await session.execute(select(IngredientMaster).limit(1))
    ingredient = result.scalars().first()
    assert ingredient is not None, "IngredientMaster가 비어 있음 - KCIA 적재 먼저 필요"
    return ingredient


def _matcher_for(ingredient: IngredientMaster) -> IngredientNameMatcher:
    candidate = IngredientCandidate(
        ingredient_id=ingredient.id,
        standard_name_ko=ingredient.standard_name_ko,
        standard_name_en=ingredient.standard_name_en,
        old_names_ko=tuple(ingredient.old_names_ko),
        old_names_en=tuple(ingredient.old_names_en),
        normalized_name_ko=ingredient.normalized_name_ko,
        normalized_name_en=ingredient.normalized_name_en,
    )
    return IngredientNameMatcher([candidate], IngredientNameNormalizer())


def _new_item(ingredient: IngredientMaster) -> MfdsRestrictedIngredientItem:
    return MfdsRestrictedIngredientItem.model_validate(
        {
            "REGULATE_TYPE": "한도",
            "INGR_STD_NAME": ingredient.standard_name_ko,
            "INGR_ENG_NAME": ingredient.standard_name_en,
            "COUNTRY_NAME": "한국",
            "LIMIT_COND": "새 데이터: 1.0% 이하",
        }
    )


@pytest.mark.asyncio
async def test_prep_phase_failure_leaves_old_data_untouched(session, tmp_path):
    # 로컬 개발 DB에 이미 실 MFDS Evidence가 적재돼 있을 수 있어 절대값이 아니라
    # "이 테스트가 시작하기 직전 대비 변화가 없다"로 비교한다.
    baseline_count = await _mfds_evidence_count(session)
    ingredient = await _one_ingredient(session)
    old_evidence = await _seed_existing_mfds_evidence(session, ingredient.id)

    service = RagIngestionService(session, _FailingEmbedder())
    matcher = _matcher_for(ingredient)

    with pytest.raises(RuntimeError):
        await service.replace_mfds_evidence_and_reindex(
            [_new_item(ingredient)], matcher, review_queue_path=tmp_path / "review_queue.csv"
        )

    # 임베딩이 실패 단계에서 죽었으니 DB 쓰기(delete/insert)는 시작도 안 됐어야 한다.
    assert await _mfds_evidence_count(session) == baseline_count + 1
    assert await _rag_chunk_count_for_evidence(session, old_evidence.id) == 1


@pytest.mark.asyncio
async def test_db_write_phase_failure_rolls_back_completely(session, tmp_path):
    """DB 삭제까지는 실행됐어도, 뒤이은 삽입이 실패하면 트랜잭션 전체가 롤백돼야 한다."""
    baseline_count = await _mfds_evidence_count(session)
    ingredient = await _one_ingredient(session)
    old_evidence = await _seed_existing_mfds_evidence(session, ingredient.id)

    service = RagIngestionService(session, _WrongDimensionEmbedder())
    matcher = _matcher_for(ingredient)

    nested = await session.begin_nested()
    try:
        with pytest.raises(Exception):  # noqa: B017 - DB 드라이버 예외 타입까지는 안 가린다
            await service.replace_mfds_evidence_and_reindex(
                [_new_item(ingredient)], matcher, review_queue_path=tmp_path / "review_queue.csv"
            )
            await session.flush()  # INSERT를 실제로 내보내 차원 불일치를 드러낸다
    finally:
        await nested.rollback()

    # 롤백 후에는 옛 Evidence와 옛 청크가 삭제 전 상태로 남아 있어야 한다.
    assert await _mfds_evidence_count(session) == baseline_count + 1
    assert await _rag_chunk_count_for_evidence(session, old_evidence.id) == 1
