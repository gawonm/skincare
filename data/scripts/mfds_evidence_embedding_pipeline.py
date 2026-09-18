"""chunk staging record 목록을 배치로 나눠 임베딩하고 적재하는 오케스트레이션 로직.

`MfdsEvidenceEmbedder`(실제 BGE-M3 추론)와 `MfdsEvidenceChunkLoader`(실제 DB I/O)를
직접 의존하지 않고 `Protocol`로 받는다 - 이 모듈의 배치 분할/resume/실패 격리 로직은
모델 로딩이나 DB 연결 없이 단위 테스트로 검증해야 하기 때문이다(가짜 embedder/loader로
테스트, `tests/unit/test_mfds_evidence_embedding_pipeline.py`).
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from data.scripts.mfds_evidence_backfill_schemas import EvidenceChunkStagingRecord
from data.scripts.mfds_evidence_embedding_schemas import (
    MfdsEvidenceEmbeddingFailure,
    MfdsEvidenceEmbeddingSummary,
)

DEFAULT_COMMIT_BATCH_SIZE = 16  # settings.agent.embedding.batch_size(로컬 BGE-M3) 기본값과 맞춘다.


class EmbedderProtocol(Protocol):
    async def embed_texts(self, texts: Sequence[str]) -> object: ...


class LoaderProtocol(Protocol):
    async def load_document_ids_by_source_id(self) -> dict[str, UUID]: ...

    async def load_existing_chunk_ids(self, chunk_ids: list[str]) -> set[str]: ...

    async def insert_chunk(
        self,
        record: EvidenceChunkStagingRecord,
        *,
        document_id: UUID,
        embedding: list[float],
        embedding_model: str,
    ) -> None: ...


class MfdsEvidenceEmbeddingPipeline:
    def __init__(
        self,
        embedder: EmbedderProtocol,
        loader: LoaderProtocol,
        *,
        commit_batch_size: int = DEFAULT_COMMIT_BATCH_SIZE,
    ) -> None:
        if commit_batch_size < 1:
            raise ValueError("commit_batch_size는 1 이상이어야 합니다.")
        self._embedder = embedder
        self._loader = loader
        self._commit_batch_size = commit_batch_size

    async def run(
        self, records: list[EvidenceChunkStagingRecord], *, dry_run: bool
    ) -> tuple[MfdsEvidenceEmbeddingSummary, list[MfdsEvidenceEmbeddingFailure]]:
        document_ids = await self._loader.load_document_ids_by_source_id()

        missing_document: list[EvidenceChunkStagingRecord] = []
        resolvable: list[EvidenceChunkStagingRecord] = []
        for record in records:
            if record.document_source_id in document_ids:
                resolvable.append(record)
            else:
                missing_document.append(record)

        existing_chunk_ids = await self._loader.load_existing_chunk_ids(
            [record.chunk_id for record in resolvable]
        )
        pending = [r for r in resolvable if r.chunk_id not in existing_chunk_ids]
        already_embedded_skipped = len(resolvable) - len(pending)

        failures: list[MfdsEvidenceEmbeddingFailure] = [
            MfdsEvidenceEmbeddingFailure(
                chunk_id=record.chunk_id,
                legacy_evidence_id=record.legacy_evidence_id,
                reason=f"document_source_id {record.document_source_id!r}에 해당하는 "
                "evidence_document가 없습니다(백필 미실행 또는 idempotency 조회 오류).",
                retryable=True,
            )
            for record in missing_document
        ]

        embedded_now = 0
        if not dry_run:
            for batch_start in range(0, len(pending), self._commit_batch_size):
                batch = pending[batch_start : batch_start + self._commit_batch_size]
                batch_embedded, batch_failures = await self._process_batch(batch, document_ids)
                embedded_now += batch_embedded
                failures.extend(batch_failures)

        summary = MfdsEvidenceEmbeddingSummary(
            dry_run=dry_run,
            total_staged=len(records),
            documents_missing=len(missing_document),
            already_embedded_skipped=already_embedded_skipped,
            embedded_now=embedded_now,
            failed=len(failures),
        )
        return summary, failures

    async def _process_batch(
        self, batch: list[EvidenceChunkStagingRecord], document_ids: dict[str, UUID]
    ) -> tuple[int, list[MfdsEvidenceEmbeddingFailure]]:
        try:
            result = await self._embedder.embed_texts([record.content for record in batch])
            vectors = result.vectors  # type: ignore[attr-defined]
            model_name = result.model  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 배치 전체 실패 시 건별로 재시도해 격리한다.
            return await self._process_records_individually(batch, document_ids)

        embedded = 0
        failures: list[MfdsEvidenceEmbeddingFailure] = []
        for record, vector in zip(batch, vectors, strict=True):
            try:
                await self._loader.insert_chunk(
                    record,
                    document_id=document_ids[record.document_source_id],
                    embedding=vector,
                    embedding_model=model_name,
                )
                embedded += 1
            except Exception as exc:  # noqa: BLE001 - 한 chunk 삽입 실패가 배치 전체를 막지 않는다.
                failures.append(
                    MfdsEvidenceEmbeddingFailure(
                        chunk_id=record.chunk_id,
                        legacy_evidence_id=record.legacy_evidence_id,
                        reason=f"insert 실패: {exc}",
                        retryable=True,
                    )
                )
        return embedded, failures

    async def _process_records_individually(
        self, batch: list[EvidenceChunkStagingRecord], document_ids: dict[str, UUID]
    ) -> tuple[int, list[MfdsEvidenceEmbeddingFailure]]:
        """배치 임베딩 자체가 실패했을 때 건별로 재시도해 실패한 chunk만 골라낸다."""
        embedded = 0
        failures: list[MfdsEvidenceEmbeddingFailure] = []
        for record in batch:
            try:
                result = await self._embedder.embed_texts([record.content])
                await self._loader.insert_chunk(
                    record,
                    document_id=document_ids[record.document_source_id],
                    embedding=result.vectors[0],  # type: ignore[attr-defined]
                    embedding_model=result.model,  # type: ignore[attr-defined]
                )
                embedded += 1
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    MfdsEvidenceEmbeddingFailure(
                        chunk_id=record.chunk_id,
                        legacy_evidence_id=record.legacy_evidence_id,
                        reason=str(exc),
                        retryable=True,
                    )
                )
        return embedded, failures
