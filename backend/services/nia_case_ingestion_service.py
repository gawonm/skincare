"""NIA Case JSONL을 BGE-M3로 임베딩해 PostgreSQL에 적재하는 실행 진입점.

사용 예:
    uv run python -m backend.services.nia_case_ingestion_service
"""

import argparse
import asyncio
import hashlib
import io
import sys
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.rag.ports import TextEmbedder
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingVector,
    LocalEmbeddingModel,
)
from backend.repositories.nia_case_document_repository import (
    NiaCaseDocumentRepository,
    NiaCaseDocumentUpsert,
    NiaCaseExistingDigestRequest,
)
from backend.services.nia_case_ingestion_schemas import (
    NiaCaseDatasetSplit,
    NiaCaseExportManifestInput,
    NiaCaseExportRecordInput,
    NiaCaseIngestionPayload,
    NiaCaseIngestionRequest,
    NiaCaseIngestionResult,
)
from models.nia_case_document import NiaCaseDatasetSplit as StorageDatasetSplit

DEFAULT_INPUT_PATH = Path("data/processed/nia_case_documents_10s_30s.jsonl")
DEFAULT_MANIFEST_PATH = Path("data/processed/nia_case_documents_10s_30s.manifest.json")
DEFAULT_BATCH_SIZE = 16
SHA256_READ_SIZE_BYTES = 1024 * 1024


class NiaCaseIngestionErrorCode(StrEnum):
    INPUT_NOT_FOUND = "input_not_found"
    MANIFEST_NOT_FOUND = "manifest_not_found"
    INVALID_INPUT = "invalid_input"
    MANIFEST_MISMATCH = "manifest_mismatch"
    DUPLICATE_CASE_ID = "duplicate_case_id"
    INVALID_EMBEDDING = "invalid_embedding"
    BATCH_FAILED = "batch_failed"
    INVALID_EMBEDDING_CONFIG = "invalid_embedding_config"


class NiaCaseIngestionError(RuntimeError):
    def __init__(self, code: NiaCaseIngestionErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"NIA Case 적재 실패 [{code.value}]: {message}")


class NiaCaseIngestionFileReader:
    """DB를 변경하기 전에 JSONL과 manifest 전체를 검증한다."""

    def read(self, request: NiaCaseIngestionRequest) -> NiaCaseIngestionPayload:
        self._validate_paths(request)
        manifest = self._read_manifest(request.manifest_path)
        records = self._read_records(request.input_path)
        self._validate_manifest(request.input_path, manifest, records)
        return NiaCaseIngestionPayload(records=records, manifest=manifest)

    def _validate_paths(self, request: NiaCaseIngestionRequest) -> None:
        if not request.input_path.is_file():
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.INPUT_NOT_FOUND,
                f"JSONL 파일이 없습니다: {request.input_path}",
            )
        if not request.manifest_path.is_file():
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.MANIFEST_NOT_FOUND,
                f"manifest 파일이 없습니다: {request.manifest_path}",
            )

    def _read_manifest(self, path: Path) -> NiaCaseExportManifestInput:
        try:
            return NiaCaseExportManifestInput.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.INVALID_INPUT,
                f"manifest를 읽거나 검증하지 못했습니다: {path}: {exc}",
            ) from exc

    def _read_records(self, path: Path) -> list[NiaCaseExportRecordInput]:
        records: list[NiaCaseExportRecordInput] = []
        seen_case_ids: set[str] = set()
        try:
            with path.open("r", encoding="utf-8") as input_file:
                for line_number, line in enumerate(input_file, start=1):
                    if not line.strip():
                        raise NiaCaseIngestionError(
                            NiaCaseIngestionErrorCode.INVALID_INPUT,
                            f"빈 JSONL 행이 있습니다: line={line_number}",
                        )
                    try:
                        record = NiaCaseExportRecordInput.model_validate_json(line)
                    except ValidationError as exc:
                        raise NiaCaseIngestionError(
                            NiaCaseIngestionErrorCode.INVALID_INPUT,
                            f"JSONL schema가 올바르지 않습니다: line={line_number}: {exc}",
                        ) from exc
                    if record.document.case_id in seen_case_ids:
                        raise NiaCaseIngestionError(
                            NiaCaseIngestionErrorCode.DUPLICATE_CASE_ID,
                            f"중복 case_id가 있습니다: {record.document.case_id}",
                        )
                    seen_case_ids.add(record.document.case_id)
                    records.append(record)
        except OSError as exc:
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.INVALID_INPUT,
                f"JSONL을 읽지 못했습니다: {path}: {exc}",
            ) from exc
        return records

    def _validate_manifest(
        self,
        input_path: Path,
        manifest: NiaCaseExportManifestInput,
        records: list[NiaCaseExportRecordInput],
    ) -> None:
        actual_hash = self._sha256(input_path)
        if actual_hash != manifest.output_sha256:
            self._raise_manifest_mismatch(
                f"SHA-256이 다릅니다: manifest={manifest.output_sha256}, actual={actual_hash}"
            )
        if len(records) != manifest.output_record_count:
            self._raise_manifest_mismatch(
                f"출력 건수가 다릅니다: manifest={manifest.output_record_count}, actual={len(records)}"
            )

        split_counts = Counter(record.dataset_split for record in records)
        expected_split_counts = {
            NiaCaseDatasetSplit.TRAINING: manifest.training_record_count,
            NiaCaseDatasetSplit.VALIDATION: manifest.validation_record_count,
        }
        for dataset_split, expected_count in expected_split_counts.items():
            if split_counts[dataset_split] != expected_count:
                self._raise_manifest_mismatch(
                    f"{dataset_split.value} 건수가 다릅니다: "
                    f"manifest={expected_count}, actual={split_counts[dataset_split]}"
                )

        versions = {record.document.text_version for record in records}
        if records and versions != {manifest.text_version}:
            self._raise_manifest_mismatch(
                f"text_version이 다릅니다: manifest={manifest.text_version}, actual={sorted(versions)}"
            )

        archive_counts = Counter(
            (record.source.archive_name, record.dataset_split) for record in records
        )
        expected_archives = {
            (archive.archive_name, archive.dataset_split): archive.output_record_count
            for archive in manifest.archives
        }
        if archive_counts != Counter(expected_archives):
            self._raise_manifest_mismatch(
                "archive별 출력 건수가 JSONL과 manifest에서 다릅니다."
            )

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as input_file:
            while chunk := input_file.read(SHA256_READ_SIZE_BYTES):
                digest.update(chunk)
        return digest.hexdigest()

    def _raise_manifest_mismatch(self, message: str) -> None:
        raise NiaCaseIngestionError(NiaCaseIngestionErrorCode.MANIFEST_MISMATCH, message)


class NiaCaseIngestionService:
    """변경된 사례만 임베딩하고 batch 단위로 upsert/commit한다."""

    def __init__(
        self,
        session: AsyncSession,
        embedder: TextEmbedder,
        repository: NiaCaseDocumentRepository | None = None,
        reader: NiaCaseIngestionFileReader | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._repository = repository or NiaCaseDocumentRepository(session)
        self._reader = reader or NiaCaseIngestionFileReader()

    async def ingest_jsonl(
        self, request: NiaCaseIngestionRequest
    ) -> NiaCaseIngestionResult:
        payload = self._reader.read(request)
        embedding_model = LocalEmbeddingModel.BGE_M3.value
        inserted_count = 0
        updated_count = 0
        unchanged_count = 0
        embedded_count = 0

        for start in range(0, len(payload.records), request.batch_size):
            batch = payload.records[start : start + request.batch_size]
            try:
                inserted, updated, unchanged, embedded = await self._ingest_batch(
                    batch,
                    payload.manifest.text_version,
                    embedding_model,
                )
                await self._session.commit()
            except Exception as exc:
                # 어떤 실패든 현재 batch를 확정하면 재실행 시 일부 데이터만 섞이므로 즉시 rollback한다.
                await self._session.rollback()
                if isinstance(exc, NiaCaseIngestionError):
                    raise NiaCaseIngestionError(
                        exc.code,
                        f"batch 시작 위치 {start + 1}에서 실패했습니다: {exc}",
                    ) from exc
                raise NiaCaseIngestionError(
                    NiaCaseIngestionErrorCode.BATCH_FAILED,
                    f"batch 시작 위치 {start + 1}에서 실패했습니다: {exc}",
                ) from exc
            inserted_count += inserted
            updated_count += updated
            unchanged_count += unchanged
            embedded_count += embedded

        return NiaCaseIngestionResult(
            total_count=len(payload.records),
            inserted_count=inserted_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            embedded_count=embedded_count,
            text_version=payload.manifest.text_version,
            embedding_model=embedding_model,
        )

    async def _ingest_batch(
        self,
        batch: list[NiaCaseExportRecordInput],
        text_version: str,
        embedding_model: str,
    ) -> tuple[int, int, int, int]:
        existing = await self._repository.find_existing_digests(
            NiaCaseExistingDigestRequest(
                case_ids=[record.document.case_id for record in batch],
                text_version=text_version,
                embedding_model=embedding_model,
            )
        )
        existing_hashes = {item.case_id: item.content_hash for item in existing}
        changed_records = [
            record
            for record in batch
            if existing_hashes.get(record.document.case_id)
            != self._content_hash(record.document.embedding_text)
        ]
        unchanged_count = len(batch) - len(changed_records)
        if not changed_records:
            return 0, 0, unchanged_count, 0

        embedding_result = await self._embedder.embed(
            EmbeddingRequest(
                texts=[record.document.embedding_text for record in changed_records]
            )
        )
        self._validate_embeddings(embedding_result.model, embedding_result.vectors, changed_records)
        upserts = [
            self._to_upsert(record, vector.values, embedding_model)
            for record, vector in zip(changed_records, embedding_result.vectors, strict=True)
        ]
        await self._repository.upsert_many(upserts)
        inserted_count = sum(
            1 for record in changed_records if record.document.case_id not in existing_hashes
        )
        updated_count = len(changed_records) - inserted_count
        return inserted_count, updated_count, unchanged_count, len(changed_records)

    def _validate_embeddings(
        self,
        model: str,
        vectors: list[EmbeddingVector],
        records: list[NiaCaseExportRecordInput],
    ) -> None:
        if model != LocalEmbeddingModel.BGE_M3.value:
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.INVALID_EMBEDDING,
                f"BGE-M3가 아닌 모델 결과입니다: {model}",
            )
        if len(vectors) != len(records):
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.INVALID_EMBEDDING,
                f"벡터 수가 입력 수와 다릅니다: vectors={len(vectors)}, records={len(records)}",
            )
        invalid_dimensions = [
            len(vector.values)
            for vector in vectors
            if len(vector.values) != BGE_M3_EMBEDDING_DIMENSIONS
        ]
        if invalid_dimensions:
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.INVALID_EMBEDDING,
                f"1024차원이 아닌 벡터가 있습니다: {invalid_dimensions}",
            )

    def _to_upsert(
        self,
        record: NiaCaseExportRecordInput,
        vector: list[float],
        embedding_model: str,
    ) -> NiaCaseDocumentUpsert:
        metadata = record.document.metadata
        return NiaCaseDocumentUpsert(
            case_id=record.document.case_id,
            dataset_split=StorageDatasetSplit(record.dataset_split.value),
            source_archive_name=record.source.archive_name,
            source_member_name=record.source.member_name,
            source_line_number=record.source.line_number,
            page_content=record.document.page_content,
            embedding_text=record.document.embedding_text,
            text_version=record.document.text_version,
            target_concern=metadata.target_concern,
            gender=metadata.gender,
            age=metadata.age,
            skin_type=metadata.skin_type,
            skin_concerns=metadata.skin_concerns,
            case_metadata=metadata.model_dump(mode="json"),
            content_hash=self._content_hash(record.document.embedding_text),
            embedding=vector,
            embedding_model=embedding_model,
        )

    def _content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class NiaCaseIngestionCommand:
    async def run(self, request: NiaCaseIngestionRequest) -> NiaCaseIngestionResult:
        # 단위 테스트와 schema import가 로컬 config에 종속되지 않도록 실행 시점에만 설정을 읽는다.
        from agent.rag.embedding.factory import TextEmbedderFactory
        from backend.services.agent_configuration import AgentConfigurationAssembler
        from core.config import settings
        from core.database import Database

        embedding_config = AgentConfigurationAssembler().create_two_layer_embedding(
            settings.openai, settings.agent
        )
        if (
            embedding_config.provider is not EmbeddingProvider.LOCAL
            or embedding_config.local.model is not LocalEmbeddingModel.BGE_M3
        ):
            raise NiaCaseIngestionError(
                NiaCaseIngestionErrorCode.INVALID_EMBEDDING_CONFIG,
                "config.yaml의 agent.embedding.provider는 local, model은 BAAI/bge-m3여야 합니다.",
            )
        embedder = TextEmbedderFactory().create(embedding_config)
        database = Database(settings.database)
        try:
            async with database.session_factory() as session:
                return await NiaCaseIngestionService(session, embedder).ingest_jsonl(request)
        finally:
            await database.dispose()


class NiaCaseIngestionArgumentParser:
    def create(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="NIA Case JSONL을 BGE-M3로 임베딩해 DB에 적재합니다.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
        parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
        return parser


class NiaCaseIngestionEntryPoint:
    def run(self, argv: Sequence[str] | None = None) -> int:
        self._configure_stdout()
        arguments = NiaCaseIngestionArgumentParser().create().parse_args(argv)
        request = NiaCaseIngestionRequest(
            input_path=arguments.input,
            manifest_path=arguments.manifest,
            batch_size=arguments.batch_size,
        )
        result = asyncio.run(NiaCaseIngestionCommand().run(request))
        self._print_result(result)
        return 0

    def _configure_stdout(self) -> None:
        # Windows 기본 cp949에서도 적재 결과가 깨지지 않도록 CLI 경계에서만 UTF-8로 맞춘다.
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def _print_result(self, result: NiaCaseIngestionResult) -> None:
        print("NIA Case Document DB 적재 완료")
        print(f"- 전체: {result.total_count:,}건")
        print(f"- 신규: {result.inserted_count:,}건")
        print(f"- 갱신: {result.updated_count:,}건")
        print(f"- 변경 없음: {result.unchanged_count:,}건")
        print(f"- 임베딩 실행: {result.embedded_count:,}건")
        print(f"- text_version: {result.text_version}")
        print(f"- embedding_model: {result.embedding_model}")


if __name__ == "__main__":
    raise SystemExit(NiaCaseIngestionEntryPoint().run())
