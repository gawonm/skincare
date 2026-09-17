"""Claim 저장 구조(claim_document/claim_chunk/claim_chunk_ingredient)를 실제 DB로 검증한다.

`conftest.session` 픽스처가 SAVEPOINT로 감싸므로 여기서 만든 행은 테스트가 끝나면 전부
롤백된다 - 실제 DB에 남지 않는다. migration이 아직 live에 적용되지 않은 동안에는 이 파일을
live DB에 대고 실행할 수 없다(테이블이 없음) - 별도 DB(`skincare_claim_migration_temp`)로
검증 완료(`docs/data/CLAIM_STORAGE_ERD.md`/CLAIM_STORAGE_IMPLEMENTATION_RESULT 보고 참고).
live migration 적용 후에는 `uv run pytest tests/db/test_claim_storage_migration.py`로
그대로 재실행할 수 있다.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.claim_chunk import (
    ClaimChunk,
    ClaimIngestionDecision,
    ClaimIngredientMatchingStatus,
    ClaimIngredientRefRole,
    ClaimPriority,
    ClaimStatementType,
    ClaimSupportStatus,
    claim_chunk_ingredient,
)
from models.claim_document import ClaimDatasetSplit, ClaimDocument
from models.ingredient import IngredientMaster

_FAKE_VECTOR_1024 = [0.01] * 1024


async def _seed_ingredient(session) -> IngredientMaster:
    ingredient = IngredientMaster(
        id=uuid4(),
        ingredient_code=999999,
        standard_name_ko="테스트성분",
        standard_name_en="Test Ingredient",
        normalized_name_ko="테스트성분",
        normalized_name_en="testingredient",
        source_version="test",
    )
    session.add(ingredient)
    await session.flush()
    return ingredient


async def _seed_document(
    session, *, source_record_id: str, annotation_version: str
) -> ClaimDocument:
    document = ClaimDocument(
        id=uuid4(),
        source_record_id=source_record_id,
        annotation_version=annotation_version,
        schema_version="1.1",
        dataset_split=ClaimDatasetSplit.TRAINING,
        skin_concerns_raw=["여드름/뾰루지"],
        production_ready=False,
    )
    session.add(document)
    await session.flush()
    return document


def _make_chunk(
    document_id, *, statement_id: str, content: str = "피지 조절 및 진정"
) -> ClaimChunk:
    return ClaimChunk(
        id=uuid4(),
        claim_document_id=document_id,
        statement_id=statement_id,
        statement_type=ClaimStatementType.INGREDIENT_EFFECT_CLAIM,
        content=content,
        source_spans=[{"json_path": "$.answer", "quote": content, "start": 0, "end": len(content)}],
        decision=ClaimIngestionDecision.INGESTIBLE_STRUCTURED,
        priority=ClaimPriority.PRIMARY,
        support_status=ClaimSupportStatus.UNVERIFIED,
        embedding=_FAKE_VECTOR_1024,
        embedding_model="BAAI/bge-m3",
    )


@pytest.mark.asyncio
async def test_same_record_different_annotation_version_both_insertable(session) -> None:
    """같은 source_record_id가 서로 다른 annotation_version(pilot/production 등)으로 공존 가능해야 한다."""
    record_id = f"TEST-{uuid4().hex[:8]}"
    doc_a = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-pilot-test"
    )
    doc_b = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-production-test"
    )
    assert doc_a.id != doc_b.id

    rows = (
        (
            await session.execute(
                select(ClaimDocument).where(ClaimDocument.source_record_id == record_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_duplicate_record_and_annotation_version_rejected(session) -> None:
    """같은 (source_record_id, annotation_version) 중복 insert는 UNIQUE 위반으로 실패해야 한다."""
    record_id = f"TEST-{uuid4().hex[:8]}"
    await _seed_document(session, source_record_id=record_id, annotation_version="llm-pilot-test")
    session.add(
        ClaimDocument(
            id=uuid4(),
            source_record_id=record_id,
            annotation_version="llm-pilot-test",
            schema_version="1.1",
            dataset_split=ClaimDatasetSplit.TRAINING,
            skin_concerns_raw=[],
            production_ready=False,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_same_statement_id_across_annotation_versions_both_insertable(session) -> None:
    """statement_id는 annotation run마다 재사용된다(실측 확인) - claim_document_id로만
    구분되면 같은 statement_id 문자열이 여러 claim_chunk 행에 존재할 수 있어야 한다."""
    record_id = f"TEST-{uuid4().hex[:8]}"
    doc_a = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-pilot-test"
    )
    doc_b = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-production-test"
    )

    statement_id = f"{record_id}-S001"
    session.add(_make_chunk(doc_a.id, statement_id=statement_id, content="pilot content"))
    session.add(_make_chunk(doc_b.id, statement_id=statement_id, content="production content"))
    await session.flush()

    rows = (
        (await session.execute(select(ClaimChunk).where(ClaimChunk.statement_id == statement_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_duplicate_statement_id_within_same_document_rejected(session) -> None:
    record_id = f"TEST-{uuid4().hex[:8]}"
    doc = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-pilot-test"
    )
    statement_id = f"{record_id}-S001"
    session.add(_make_chunk(doc.id, statement_id=statement_id))
    await session.flush()

    session.add(_make_chunk(doc.id, statement_id=statement_id))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_claim_document_roundtrip_no_information_loss(session) -> None:
    """FROZEN ClaimDocument(Pydantic) 하나를 claim_document+claim_chunk로 나눠 저장한 뒤,
    다시 읽었을 때 모든 필드가 그대로 복원되는지 확인한다."""
    record_id = f"TEST-{uuid4().hex[:8]}"
    document = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-pilot-test"
    )
    quote = "나이아신아마이드는 피지 조절과 장벽 강화에 도움을 줍니다."
    chunk = _make_chunk(
        document.id, statement_id=f"{record_id}-S005", content="피지 조절 및 장벽 강화"
    )
    chunk.source_spans = [
        {"json_path": "$.chain_of_thought[1].content", "quote": quote, "start": 10, "end": 40}
    ]
    session.add(chunk)
    await session.flush()

    reloaded_chunk = (
        await session.execute(select(ClaimChunk).where(ClaimChunk.id == chunk.id))
    ).scalar_one()
    reloaded_document = (
        await session.execute(select(ClaimDocument).where(ClaimDocument.id == document.id))
    ).scalar_one()

    assert reloaded_chunk.statement_id == f"{record_id}-S005"
    assert reloaded_chunk.statement_type == ClaimStatementType.INGREDIENT_EFFECT_CLAIM
    assert reloaded_chunk.content == "피지 조절 및 장벽 강화"
    assert reloaded_chunk.source_spans[0]["quote"] == quote
    assert reloaded_chunk.decision == ClaimIngestionDecision.INGESTIBLE_STRUCTURED
    assert reloaded_chunk.priority == ClaimPriority.PRIMARY
    assert reloaded_chunk.support_status == ClaimSupportStatus.UNVERIFIED
    assert reloaded_document.source_record_id == record_id
    assert reloaded_document.skin_concerns_raw == ["여드름/뾰루지"]
    assert reloaded_document.dataset_split == ClaimDatasetSplit.TRAINING


@pytest.mark.asyncio
async def test_ingredient_linkage_all_four_matching_statuses_storable(session) -> None:
    record_id = f"TEST-{uuid4().hex[:8]}"
    document = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-pilot-test"
    )
    chunk = _make_chunk(document.id, statement_id=f"{record_id}-S001")
    session.add(chunk)
    await session.flush()

    ingredient = await _seed_ingredient(session)

    await session.execute(
        claim_chunk_ingredient.insert().values(
            [
                {
                    "id": uuid4(),
                    "claim_chunk_id": chunk.id,
                    "ingredient_id": ingredient.id,
                    "raw_name": "테스트성분",
                    "matching_status": ClaimIngredientMatchingStatus.MATCHED,
                    "role": ClaimIngredientRefRole.UNSPECIFIED,
                },
                {
                    "id": uuid4(),
                    "claim_chunk_id": chunk.id,
                    "ingredient_id": None,
                    "raw_name": "미확인성분",
                    "matching_status": ClaimIngredientMatchingStatus.UNRESOLVED,
                    "role": ClaimIngredientRefRole.UNSPECIFIED,
                },
                {
                    "id": uuid4(),
                    "claim_chunk_id": chunk.id,
                    "ingredient_id": None,
                    "raw_name": "대나무 추출물",
                    "matching_status": ClaimIngredientMatchingStatus.UNRESOLVED_AMBIGUOUS_FAMILY,
                    "role": ClaimIngredientRefRole.UNSPECIFIED,
                },
                {
                    "id": uuid4(),
                    "claim_chunk_id": chunk.id,
                    "ingredient_id": None,
                    "raw_name": "거부된성분",
                    "matching_status": ClaimIngredientMatchingStatus.REJECTED,
                    "role": ClaimIngredientRefRole.UNSPECIFIED,
                },
            ]
        )
    )
    await session.flush()

    rows = (
        await session.execute(
            select(claim_chunk_ingredient).where(
                claim_chunk_ingredient.c.claim_chunk_id == chunk.id
            )
        )
    ).all()
    statuses = {row.matching_status for row in rows}
    assert statuses == {
        ClaimIngredientMatchingStatus.MATCHED,
        ClaimIngredientMatchingStatus.UNRESOLVED,
        ClaimIngredientMatchingStatus.UNRESOLVED_AMBIGUOUS_FAMILY,
        ClaimIngredientMatchingStatus.REJECTED,
    }


@pytest.mark.asyncio
async def test_ingredient_linkage_rejects_null_ingredient_id_and_raw_name(session) -> None:
    record_id = f"TEST-{uuid4().hex[:8]}"
    document = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-pilot-test"
    )
    chunk = _make_chunk(document.id, statement_id=f"{record_id}-S001")
    session.add(chunk)
    await session.flush()

    with pytest.raises(IntegrityError):
        await session.execute(
            claim_chunk_ingredient.insert().values(
                id=uuid4(),
                claim_chunk_id=chunk.id,
                ingredient_id=None,
                raw_name=None,
                matching_status=ClaimIngredientMatchingStatus.UNRESOLVED,
                role=ClaimIngredientRefRole.UNSPECIFIED,
            )
        )


@pytest.mark.asyncio
async def test_bge_dimension_enforced_by_db(session) -> None:
    """claim_chunk.embedding은 vector(1024) - 다른 차원을 넣으면 DB가 거부해야 한다
    (test_mfds_replace_rollback.py와 동일 관례 - mock 대신 실제 DB 제약 이용)."""
    record_id = f"TEST-{uuid4().hex[:8]}"
    document = await _seed_document(
        session, source_record_id=record_id, annotation_version="llm-pilot-test"
    )
    chunk = _make_chunk(document.id, statement_id=f"{record_id}-S001")
    chunk.embedding = [0.0] * 1536  # OpenAI 차원 - BGE-M3 컬럼에 넣으면 안 된다
    session.add(chunk)
    with pytest.raises(Exception):  # noqa: B017 - pgvector가 DBAPIError 계열로 던짐, dialect 무관하게 잡는다
        await session.flush()
