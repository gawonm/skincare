import hashlib
from collections import Counter
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from agent.rag.ports import TextEmbedder
from agent.rag.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingVector,
    LocalEmbeddingModel,
)
from backend.repositories.nia_case_document_repository import (
    NiaCaseDocumentRepository,
    NiaCaseDocumentUpsert,
    NiaCaseExistingDigest,
    NiaCaseExistingDigestRequest,
)
from backend.services.nia_case_ingestion_schemas import (
    NiaCaseArchiveManifestEntryInput,
    NiaCaseDatasetSplit,
    NiaCaseDocumentInput,
    NiaCaseExportManifestInput,
    NiaCaseExportRecordInput,
    NiaCaseIngestionRequest,
    NiaCaseMetadataInput,
    NiaCaseSourceInput,
)
from backend.services.nia_case_ingestion_service import (
    NiaCaseIngestionError,
    NiaCaseIngestionErrorCode,
    NiaCaseIngestionFileReader,
    NiaCaseIngestionService,
)
from models.nia_case_document import NIA_CASE_EMBEDDING_DIMENSION
from models.nia_case_document import NiaCaseDatasetSplit as StorageDatasetSplit


class FakeNiaCaseEmbedder(TextEmbedder):
    def __init__(self) -> None:
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self.requests.append(request)
        return EmbeddingResult(
            model=LocalEmbeddingModel.BGE_M3.value,
            vectors=[
                EmbeddingVector(values=[float(index)] * NIA_CASE_EMBEDDING_DIMENSION)
                for index, _ in enumerate(request.texts, start=1)
            ],
        )


class FakeNiaCaseDocumentRepository(NiaCaseDocumentRepository):
    def __init__(self, existing_hashes: dict[str, str] | None = None) -> None:
        self.existing_hashes = existing_hashes or {}
        self.upserts: list[NiaCaseDocumentUpsert] = []

    async def find_existing_digests(
        self, request: NiaCaseExistingDigestRequest
    ) -> list[NiaCaseExistingDigest]:
        return [
            NiaCaseExistingDigest(case_id=case_id, content_hash=self.existing_hashes[case_id])
            for case_id in request.case_ids
            if case_id in self.existing_hashes
        ]

    async def upsert_many(self, records: list[NiaCaseDocumentUpsert]) -> int:
        self.upserts.extend(records)
        return len(records)


class NiaCaseIngestionFixture:
    def record(
        self,
        case_id: str,
        dataset_split: NiaCaseDatasetSplit = NiaCaseDatasetSplit.TRAINING,
    ) -> NiaCaseExportRecordInput:
        metadata = NiaCaseMetadataInput(
            case_id=case_id,
            source_survey_id=f"survey-{case_id}",
            image_filename=f"{case_id}.jpg",
            evidence_sources=[],
            target_concern="모공",
            gender="여성",
            age=25,
            skin_type="지성",
            skin_concerns=["모공", "피지"],
            initial_skin_condition="피지가 많음",
            external=[],
        )
        return NiaCaseExportRecordInput(
            dataset_split=dataset_split,
            source=NiaCaseSourceInput(
                archive_name=f"{dataset_split.value}.zip",
                member_name="records.jsonl",
                line_number=1,
            ),
            document=NiaCaseDocumentInput(
                case_id=case_id,
                page_content=f"[질문]\n질문 {case_id}\n[답변]\n답변 {case_id}",
                embedding_text=f"[질문]\n질문 {case_id}\n[답변]\n답변 {case_id}",
                text_version="nia_case_text/v1",
                metadata=metadata,
            ),
        )

    def write(
        self, tmp_path: Path, records: list[NiaCaseExportRecordInput]
    ) -> NiaCaseIngestionRequest:
        input_path = tmp_path / "cases.jsonl"
        manifest_path = tmp_path / "cases.manifest.json"
        text = "".join(f"{record.model_dump_json()}\n" for record in records)
        input_path.write_text(text, encoding="utf-8", newline="\n")
        split_counts = Counter(record.dataset_split for record in records)
        archive_counts = Counter(
            (record.source.archive_name, record.dataset_split) for record in records
        )
        manifest = NiaCaseExportManifestInput(
            text_version="nia_case_text/v1",
            input_archive_count=len(archive_counts),
            input_record_count=len(records),
            output_record_count=len(records),
            training_record_count=split_counts[NiaCaseDatasetSplit.TRAINING],
            validation_record_count=split_counts[NiaCaseDatasetSplit.VALIDATION],
            archives=[
                NiaCaseArchiveManifestEntryInput(
                    archive_name=archive_name,
                    dataset_split=dataset_split,
                    input_record_count=count,
                    output_record_count=count,
                )
                for (archive_name, dataset_split), count in archive_counts.items()
            ],
            output_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
        )
        manifest_path.write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8", newline="\n"
        )
        return NiaCaseIngestionRequest(
            input_path=input_path,
            manifest_path=manifest_path,
            batch_size=2,
        )


class TestNiaCaseIngestionFileReader:
    def test_manifest와_jsonl을_함께_검증한다(self, tmp_path: Path) -> None:
        fixture = NiaCaseIngestionFixture()
        request = fixture.write(
            tmp_path,
            [
                fixture.record("case-1"),
                fixture.record("case-2", NiaCaseDatasetSplit.VALIDATION),
            ],
        )

        payload = NiaCaseIngestionFileReader().read(request)

        assert [record.document.case_id for record in payload.records] == ["case-1", "case-2"]
        assert payload.manifest.output_record_count == 2

    def test_jsonl이_바뀌면_manifest_hash_오류로_중단한다(self, tmp_path: Path) -> None:
        fixture = NiaCaseIngestionFixture()
        request = fixture.write(tmp_path, [fixture.record("case-1")])
        changed_text = request.input_path.read_text(encoding="utf-8").replace(
            "case-1", "case-x"
        )
        request.input_path.write_text(changed_text, encoding="utf-8", newline="\n")

        with pytest.raises(NiaCaseIngestionError) as error:
            NiaCaseIngestionFileReader().read(request)

        assert error.value.code is NiaCaseIngestionErrorCode.MANIFEST_MISMATCH


class TestNiaCaseIngestionService:
    @pytest.mark.asyncio
    async def test_신규_case만_임베딩하고_batch를_commit한다(self, tmp_path: Path) -> None:
        fixture = NiaCaseIngestionFixture()
        request = fixture.write(tmp_path, [fixture.record("case-1"), fixture.record("case-2")])
        session = AsyncMock(spec=AsyncSession)
        embedder = FakeNiaCaseEmbedder()
        repository = FakeNiaCaseDocumentRepository()
        service = NiaCaseIngestionService(
            cast(AsyncSession, session),
            embedder,
            repository=repository,
        )

        result = await service.ingest_jsonl(request)

        assert result.inserted_count == 2
        assert result.updated_count == 0
        assert result.unchanged_count == 0
        assert result.embedded_count == 2
        assert len(embedder.requests) == 1
        assert len(repository.upserts) == 2
        assert len(repository.upserts[0].embedding) == NIA_CASE_EMBEDDING_DIMENSION
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hash가_같은_case는_재임베딩하지_않는다(self, tmp_path: Path) -> None:
        fixture = NiaCaseIngestionFixture()
        record = fixture.record("case-1")
        request = fixture.write(tmp_path, [record])
        content_hash = hashlib.sha256(record.document.embedding_text.encode("utf-8")).hexdigest()
        session = AsyncMock(spec=AsyncSession)
        embedder = FakeNiaCaseEmbedder()
        repository = FakeNiaCaseDocumentRepository({"case-1": content_hash})
        service = NiaCaseIngestionService(
            cast(AsyncSession, session),
            embedder,
            repository=repository,
        )

        result = await service.ingest_jsonl(request)

        assert result.inserted_count == 0
        assert result.updated_count == 0
        assert result.unchanged_count == 1
        assert result.embedded_count == 0
        assert embedder.requests == []
        assert repository.upserts == []
        session.commit.assert_awaited_once()


class TestNiaCaseDocumentRepository:
    @pytest.mark.asyncio
    async def test_upsert는_승인된_자연키로_conflict를_처리한다(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        repository = NiaCaseDocumentRepository(cast(AsyncSession, session))
        record = NiaCaseDocumentUpsert(
            case_id="case-1",
            dataset_split=StorageDatasetSplit.TRAINING,
            source_archive_name="training.zip",
            source_member_name="records.jsonl",
            source_line_number=1,
            page_content="본문",
            embedding_text="본문",
            text_version="nia_case_text/v1",
            target_concern="모공",
            gender="여성",
            age=25,
            skin_type="지성",
            skin_concerns=["모공"],
            case_metadata={"case_id": "case-1"},
            content_hash=hashlib.sha256("본문".encode()).hexdigest(),
            embedding=[0.0] * NIA_CASE_EMBEDDING_DIMENSION,
            embedding_model=LocalEmbeddingModel.BGE_M3.value,
        )

        count = await repository.upsert_many([record])

        statement = session.execute.await_args.args[0]
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        assert count == 1
        assert "ON CONFLICT ON CONSTRAINT uq_nia_case_document_case_text_model" in compiled
        session.execute.assert_awaited_once()
