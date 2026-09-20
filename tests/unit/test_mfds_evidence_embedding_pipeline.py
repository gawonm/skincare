"""`MfdsEvidenceEmbeddingPipeline` 단위 테스트. 실제 BGE-M3 모델이나 DB 없이 가짜
embedder/loader로 배치 분할·resume·실패 격리 로직만 검증한다(실제 모델 검증은
`tests/unit/test_mfds_evidence_embedder.py`와 수동 smoke가 담당).
"""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from data.scripts.mfds_evidence_backfill_schemas import EvidenceChunkStagingRecord
from data.scripts.mfds_evidence_embedding_pipeline import MfdsEvidenceEmbeddingPipeline
from models.evidence_document import EvidenceDocumentSourceType, EvidenceLevel

_DOCUMENT_SOURCE_ID = "restricted_ingredient:한국"
_DOCUMENT_ID = uuid4()


def _staging_record(
    *, legacy_evidence_id: UUID | None = None, content: str = "claim text", chunk_index: int = 0
) -> EvidenceChunkStagingRecord:
    legacy_id = legacy_evidence_id or uuid4()
    return EvidenceChunkStagingRecord(
        document_source_id=_DOCUMENT_SOURCE_ID,
        chunk_id=f"{_DOCUMENT_SOURCE_ID}:{legacy_id}",
        source_type=EvidenceDocumentSourceType.MFDS,
        source_title="식품의약품안전처 화장품 사용제한 원료정보",
        chunk_index=chunk_index,
        content=content,
        content_hash="deadbeef",
        parser_version="mfds-evidence-backfill-v1",
        url="https://www.data.go.kr/data/15111772/openapi.do",
        jurisdiction="한국",
        evidence_level=EvidenceLevel.OFFICIAL_REGULATORY,
        legacy_evidence_id=legacy_id,
        ingredient_id=uuid4(),
    )


@dataclass
class _FakeEmbeddingResult:
    model: str
    vectors: list[list[float]]


@dataclass
class _FakeEmbedder:
    """content가 `fail_on`에 있으면 예외를 던진다. 그 외는 결정적 더미 벡터를 만든다."""

    fail_on: set[str] = field(default_factory=set)
    call_count: int = 0

    async def embed_texts(self, texts):
        self.call_count += 1
        if any(text in self.fail_on for text in texts):
            raise RuntimeError("임베딩 실패 시뮬레이션")
        return _FakeEmbeddingResult(model="BAAI/bge-m3", vectors=[[0.1] * 1024 for _ in texts])


@dataclass
class _FakeLoader:
    document_ids: dict[str, UUID]
    existing_chunk_ids: set[str] = field(default_factory=set)
    fail_insert_chunk_ids: set[str] = field(default_factory=set)
    inserted: list[dict] = field(default_factory=list)
    commit_count: int = 0

    async def load_document_ids_by_source_id(self):
        return self.document_ids

    async def load_existing_chunk_ids(self, chunk_ids):
        return {cid for cid in chunk_ids if cid in self.existing_chunk_ids}

    async def commit(self):
        self.commit_count += 1

    async def insert_chunk(self, record, *, document_id, embedding, embedding_model):
        if record.chunk_id in self.fail_insert_chunk_ids:
            raise RuntimeError("DB insert 실패 시뮬레이션")
        self.inserted.append(
            {
                "chunk_id": record.chunk_id,
                "document_id": document_id,
                "embedding": embedding,
                "embedding_model": embedding_model,
                "ingredient_id": record.ingredient_id,
            }
        )


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_embedder_or_insert(self) -> None:
        record = _staging_record()
        embedder = _FakeEmbedder()
        loader = _FakeLoader(document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID})
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader)

        summary, failures = await pipeline.run([record], dry_run=True)

        assert embedder.call_count == 0
        assert loader.inserted == []
        assert summary.embedded_now == 0
        assert summary.total_staged == 1
        assert failures == []


class TestDocumentLinkage:
    @pytest.mark.asyncio
    async def test_missing_document_is_reported_as_failure(self) -> None:
        record = _staging_record()
        embedder = _FakeEmbedder()
        loader = _FakeLoader(document_ids={})  # PR #33 백필 미실행 상황 시뮬레이션
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader)

        summary, failures = await pipeline.run([record], dry_run=False)

        assert summary.documents_missing == 1
        assert summary.embedded_now == 0
        assert len(failures) == 1
        assert failures[0].chunk_id == record.chunk_id

    @pytest.mark.asyncio
    async def test_resolved_document_id_passed_to_insert(self) -> None:
        record = _staging_record()
        embedder = _FakeEmbedder()
        loader = _FakeLoader(document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID})
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader)

        await pipeline.run([record], dry_run=False)

        assert loader.inserted[0]["document_id"] == _DOCUMENT_ID


class TestIdempotencyAndResume:
    @pytest.mark.asyncio
    async def test_already_embedded_chunk_is_skipped(self) -> None:
        record = _staging_record()
        embedder = _FakeEmbedder()
        loader = _FakeLoader(
            document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID},
            existing_chunk_ids={record.chunk_id},
        )
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader)

        summary, failures = await pipeline.run([record], dry_run=False)

        assert summary.already_embedded_skipped == 1
        assert summary.embedded_now == 0
        assert embedder.call_count == 0
        assert loader.inserted == []
        assert failures == []

    @pytest.mark.asyncio
    async def test_partial_resume_only_embeds_remaining(self) -> None:
        done = _staging_record()
        pending = _staging_record()
        embedder = _FakeEmbedder()
        loader = _FakeLoader(
            document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID},
            existing_chunk_ids={done.chunk_id},
        )
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader)

        summary, _ = await pipeline.run([done, pending], dry_run=False)

        assert summary.already_embedded_skipped == 1
        assert summary.embedded_now == 1
        assert loader.inserted[0]["chunk_id"] == pending.chunk_id


class TestBatching:
    @pytest.mark.asyncio
    async def test_records_split_across_commit_batch_size(self) -> None:
        records = [_staging_record(content=f"text-{i}") for i in range(5)]
        embedder = _FakeEmbedder()
        loader = _FakeLoader(document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID})
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader, commit_batch_size=2)

        summary, failures = await pipeline.run(records, dry_run=False)

        assert summary.embedded_now == 5
        assert failures == []
        assert embedder.call_count == 3  # 2 + 2 + 1
        # 배치마다 커밋해야 중간에 죽어도 그 배치까지는 DB에 남는다
        assert loader.commit_count == 3


class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_one_bad_embedding_in_batch_does_not_block_others(self) -> None:
        good_1 = _staging_record(content="good-1")
        bad = _staging_record(content="BAD")
        good_2 = _staging_record(content="good-2")
        embedder = _FakeEmbedder(fail_on={"BAD"})
        loader = _FakeLoader(document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID})
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader, commit_batch_size=10)

        summary, failures = await pipeline.run([good_1, bad, good_2], dry_run=False)

        assert summary.embedded_now == 2
        assert summary.failed == 1
        assert failures[0].chunk_id == bad.chunk_id
        assert failures[0].retryable is True
        inserted_ids = {row["chunk_id"] for row in loader.inserted}
        assert inserted_ids == {good_1.chunk_id, good_2.chunk_id}

    @pytest.mark.asyncio
    async def test_one_bad_insert_does_not_block_others(self) -> None:
        good = _staging_record(content="good")
        bad = _staging_record(content="also-good-embedding-but-db-fails")
        embedder = _FakeEmbedder()
        loader = _FakeLoader(
            document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID},
            fail_insert_chunk_ids={bad.chunk_id},
        )
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader, commit_batch_size=10)

        summary, failures = await pipeline.run([good, bad], dry_run=False)

        assert summary.embedded_now == 1
        assert summary.failed == 1
        assert failures[0].chunk_id == bad.chunk_id


class TestProvenance:
    @pytest.mark.asyncio
    async def test_embedding_model_recorded_on_insert(self) -> None:
        record = _staging_record()
        embedder = _FakeEmbedder()
        loader = _FakeLoader(document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID})
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader)

        await pipeline.run([record], dry_run=False)

        assert loader.inserted[0]["embedding_model"] == "BAAI/bge-m3"

    @pytest.mark.asyncio
    async def test_ingredient_id_preserved_on_insert(self) -> None:
        record = _staging_record()
        embedder = _FakeEmbedder()
        loader = _FakeLoader(document_ids={_DOCUMENT_SOURCE_ID: _DOCUMENT_ID})
        pipeline = MfdsEvidenceEmbeddingPipeline(embedder, loader)

        await pipeline.run([record], dry_run=False)

        assert loader.inserted[0]["ingredient_id"] == record.ingredient_id


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
