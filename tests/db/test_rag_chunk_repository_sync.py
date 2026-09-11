"""`RagChunkRepository.sync_documents`를 실제 로컬 DB로 검증한다. OpenAI 호출 없음.

`nia_qa` 소스로 테스트하는 이유: `evidence_id`/`ingredient_knowledge_fact_id`는 FK라
실제 존재하는 행이 있어야 하지만, `nia_record_id`는 FK가 아닌 평문 문자열이라 사전 준비
없이 바로 테스트할 수 있다 - 검증 대상인 sync_documents의 교체 로직 자체는 세 소스 모두
같은 코드 경로를 타므로 이걸로 충분하다.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.repositories.rag_chunk_repository import RagChunkInsert, RagChunkRepository
from models.rag_chunk import RagChunk, RagChunkField, RagConfidenceTier, RagSourceTable


def _insert(
    record_id: str, chunk_field: RagChunkField, content: str, chunk_index: int = 0
) -> RagChunkInsert:
    return RagChunkInsert(
        ingredient_id=None,
        source_table=RagSourceTable.NIA_QA,
        evidence_id=None,
        ingredient_knowledge_fact_id=None,
        nia_record_id=record_id,
        chunk_field=chunk_field,
        chunk_index=chunk_index,
        content=content,
        embedding=[0.0] * 1536,
        embedding_model="fake-test-model",
        confidence_tier=RagConfidenceTier.AI_GENERATED_REVIEWED,
        cites_cir=False,
        source_title="테스트 출처",
        source_url=None,
        citation_refs=[],
    )


async def _chunks_for(session, record_id: str) -> list[RagChunk]:
    result = await session.execute(select(RagChunk).where(RagChunk.nia_record_id == record_id))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_first_sync_inserts_all_chunks(session):
    repo = RagChunkRepository(session)
    record_id = str(uuid4())
    inserts = [
        _insert(record_id, RagChunkField.NIA_QUESTION, "질문"),
        _insert(record_id, RagChunkField.NIA_ANSWER, "답변"),
    ]

    result = await repo.sync_documents(RagSourceTable.NIA_QA, [record_id], inserts)

    assert result.inserted == 2
    assert result.updated == 0
    assert result.deleted == 0
    assert len(await _chunks_for(session, record_id)) == 2


@pytest.mark.asyncio
async def test_resync_with_no_changes_is_a_noop(session):
    repo = RagChunkRepository(session)
    record_id = str(uuid4())
    inserts = [_insert(record_id, RagChunkField.NIA_QUESTION, "질문")]
    await repo.sync_documents(RagSourceTable.NIA_QA, [record_id], inserts)

    result = await repo.sync_documents(RagSourceTable.NIA_QA, [record_id], inserts)

    assert result.inserted == 0
    assert result.updated == 0
    assert result.unchanged == 1
    assert result.deleted == 0


@pytest.mark.asyncio
async def test_resync_updates_only_changed_content(session):
    repo = RagChunkRepository(session)
    record_id = str(uuid4())
    await repo.sync_documents(
        RagSourceTable.NIA_QA,
        [record_id],
        [
            _insert(record_id, RagChunkField.NIA_QUESTION, "질문"),
            _insert(record_id, RagChunkField.NIA_ANSWER, "옛날 답변"),
        ],
    )

    result = await repo.sync_documents(
        RagSourceTable.NIA_QA,
        [record_id],
        [
            _insert(record_id, RagChunkField.NIA_QUESTION, "질문"),
            _insert(record_id, RagChunkField.NIA_ANSWER, "새 답변"),
        ],
    )

    assert result.unchanged == 1
    assert result.updated == 1
    chunks = {c.chunk_field: c.content for c in await _chunks_for(session, record_id)}
    assert chunks[RagChunkField.NIA_ANSWER] == "새 답변"


@pytest.mark.asyncio
async def test_resync_deletes_chunks_for_removed_fields(session):
    """원본에서 필드가 사라지면(청크 수가 줄면) 그 청크는 삭제돼야 한다."""
    repo = RagChunkRepository(session)
    record_id = str(uuid4())
    await repo.sync_documents(
        RagSourceTable.NIA_QA,
        [record_id],
        [
            _insert(record_id, RagChunkField.NIA_QUESTION, "질문"),
            _insert(record_id, RagChunkField.NIA_ANSWER, "답변"),
        ],
    )

    # 답변 필드가 이번에는 비어서 새 청크 목록에 없다.
    result = await repo.sync_documents(
        RagSourceTable.NIA_QA, [record_id], [_insert(record_id, RagChunkField.NIA_QUESTION, "질문")]
    )

    assert result.deleted == 1
    remaining = await _chunks_for(session, record_id)
    assert len(remaining) == 1
    assert remaining[0].chunk_field == RagChunkField.NIA_QUESTION


@pytest.mark.asyncio
async def test_sync_never_touches_documents_outside_fetched_refs(session):
    """fetched_refs에 없는 문서는 새 청크 목록이 그 문서를 안 담고 있어도 그대로 둔다."""
    repo = RagChunkRepository(session)
    untouched_id = str(uuid4())
    other_id = str(uuid4())
    await repo.sync_documents(
        RagSourceTable.NIA_QA,
        [untouched_id],
        [_insert(untouched_id, RagChunkField.NIA_QUESTION, "원본")],
    )

    # other_id만 조회에 성공했다고 알려준다 - untouched_id는 fetched_refs에 없다.
    await repo.sync_documents(
        RagSourceTable.NIA_QA,
        [other_id],
        [_insert(other_id, RagChunkField.NIA_QUESTION, "다른 문서")],
    )

    untouched_chunks = await _chunks_for(session, untouched_id)
    assert len(untouched_chunks) == 1
    assert untouched_chunks[0].content == "원본"


@pytest.mark.asyncio
async def test_empty_fetched_refs_is_a_full_noop(session):
    repo = RagChunkRepository(session)
    result = await repo.sync_documents(RagSourceTable.NIA_QA, [], [])
    assert result == type(result)(inserted=0, updated=0, unchanged=0, deleted=0)


@pytest.mark.asyncio
async def test_failed_transaction_leaves_no_partial_writes(session):
    """DB 쓰기 도중 실패하면(트랜잭션 롤백) 그 배치의 변경이 하나도 반영되지 않아야 한다."""
    repo = RagChunkRepository(session)
    record_id = str(uuid4())

    nested = await session.begin_nested()
    try:
        await repo.sync_documents(
            RagSourceTable.NIA_QA,
            [record_id],
            [_insert(record_id, RagChunkField.NIA_QUESTION, "질문")],
        )
        raise RuntimeError("DB 쓰기 단계 실패를 흉내낸다")
    except RuntimeError:
        await nested.rollback()

    assert await _chunks_for(session, record_id) == []
