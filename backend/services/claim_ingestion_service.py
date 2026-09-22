"""NIA Claim export JSONL을 BGE-M3로 임베딩해 Claim 저장소에 적재한다.

사용 예:
    uv run python -m backend.services.claim_ingestion_service
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
from typing import ClassVar

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
from backend.repositories.claim_chunk_ingredient_repository import (
    ClaimChunkIngredientRepository,
    ClaimChunkIngredientUpsert,
)
from backend.repositories.claim_chunk_repository import (
    ClaimChunkRepository,
    ClaimChunkUpsert,
    ClaimSourceSpanValue,
)
from backend.repositories.claim_document_repository import (
    ClaimDocumentRepository,
    ClaimDocumentUpsert,
)
from backend.services.claim_ingestion_schemas import (
    ClaimEmbeddingTarget,
    ClaimExportManifestInput,
    ClaimExportRecordInput,
    ClaimIngestionPayload,
    ClaimIngestionRequest,
    ClaimIngestionResult,
    ClaimStatementInput,
)
from models.claim_chunk import ClaimIngestionDecision
from models.claim_document import ClaimDatasetSplit

DEFAULT_INPUT_PATH = Path("data/processed/nia_claim_documents_production.jsonl")
DEFAULT_MANIFEST_PATH = Path("data/processed/nia_claim_documents_production.manifest.json")
DEFAULT_BATCH_SIZE = 16
SHA256_READ_SIZE_BYTES = 1024 * 1024
CLAIM_EXPORT_VERSION = "nia_claim_export/v1"


class ClaimIngestionErrorCode(StrEnum):
    INPUT_NOT_FOUND = "input_not_found"
    MANIFEST_NOT_FOUND = "manifest_not_found"
    INVALID_INPUT = "invalid_input"
    MANIFEST_MISMATCH = "manifest_mismatch"
    DUPLICATE_DOCUMENT = "duplicate_document"
    INVALID_EMBEDDING = "invalid_embedding"
    INVALID_EMBEDDING_CONFIG = "invalid_embedding_config"
    BATCH_FAILED = "batch_failed"


class ClaimIngestionError(RuntimeError):
    def __init__(self, code: ClaimIngestionErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"NIA Claim 적재 실패 [{code.value}]: {message}")


class ClaimIngestionFileReader:
    def read(self, request: ClaimIngestionRequest) -> ClaimIngestionPayload:
        self._validate_paths(request)
        manifest = self._read_manifest(request.manifest_path)
        records = self._read_records(request.input_path)
        self._validate_manifest(request.input_path, manifest, records)
        return ClaimIngestionPayload(records=records, manifest=manifest)

    def _validate_paths(self, request: ClaimIngestionRequest) -> None:
        if not request.input_path.is_file():
            raise ClaimIngestionError(
                ClaimIngestionErrorCode.INPUT_NOT_FOUND,
                f"Claim JSONL 파일이 없습니다: {request.input_path}",
            )
        if not request.manifest_path.is_file():
            raise ClaimIngestionError(
                ClaimIngestionErrorCode.MANIFEST_NOT_FOUND,
                f"Claim manifest 파일이 없습니다: {request.manifest_path}",
            )

    def _read_manifest(self, path: Path) -> ClaimExportManifestInput:
        try:
            return ClaimExportManifestInput.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise ClaimIngestionError(
                ClaimIngestionErrorCode.INVALID_INPUT,
                f"Claim manifest를 읽거나 검증하지 못했습니다: {path}: {exc}",
            ) from exc

    def _read_records(self, path: Path) -> list[ClaimExportRecordInput]:
        records: list[ClaimExportRecordInput] = []
        seen_keys: set[tuple[str, str]] = set()
        with path.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                try:
                    record = ClaimExportRecordInput.model_validate_json(line)
                except ValidationError as exc:
                    raise ClaimIngestionError(
                        ClaimIngestionErrorCode.INVALID_INPUT,
                        f"Claim JSONL 스키마 오류: {path}:{line_number}: {exc}",
                    ) from exc
                key = (record.source_record_id, record.annotation_version)
                if key in seen_keys:
                    raise ClaimIngestionError(
                        ClaimIngestionErrorCode.DUPLICATE_DOCUMENT,
                        f"Claim document 자연키 중복: {key}",
                    )
                seen_keys.add(key)
                records.append(record)
        return records

    def _validate_manifest(
        self,
        input_path: Path,
        manifest: ClaimExportManifestInput,
        records: list[ClaimExportRecordInput],
    ) -> None:
        if manifest.export_version != CLAIM_EXPORT_VERSION:
            self._raise_manifest_mismatch(
                f"지원하지 않는 export_version입니다: {manifest.export_version}"
            )
        actual_hash = self._sha256(input_path)
        if manifest.output_sha256 != actual_hash:
            self._raise_manifest_mismatch(
                f"SHA-256 불일치: manifest={manifest.output_sha256}, actual={actual_hash}"
            )
        if manifest.document_count != len(records):
            self._raise_manifest_mismatch(
                f"document 건수 불일치: manifest={manifest.document_count}, actual={len(records)}"
            )
        versions = {record.annotation_version for record in records}
        if versions != {manifest.annotation_version}:
            self._raise_manifest_mismatch(
                f"annotation_version 불일치: manifest={manifest.annotation_version}, actual={versions}"
            )
        statements = [statement for record in records for statement in record.statements]
        if len(statements) != manifest.statement_count:
            self._raise_manifest_mismatch("statement 건수가 manifest와 다릅니다.")
        decision_counts = Counter(statement.decision for statement in statements)
        ingestible_count = sum(
            decision_counts[decision] for decision in ClaimIngestionService.INGESTIBLE_DECISIONS
        )
        if ingestible_count != manifest.ingestible_statement_count:
            self._raise_manifest_mismatch("적재 가능 statement 건수가 manifest와 다릅니다.")
        if decision_counts[ClaimIngestionDecision.BLOCKED] != manifest.blocked_statement_count:
            self._raise_manifest_mismatch("blocked statement 건수가 manifest와 다릅니다.")
        if (
            decision_counts[ClaimIngestionDecision.HUMAN_REVIEW]
            != manifest.human_review_statement_count
        ):
            self._raise_manifest_mismatch("human_review statement 건수가 manifest와 다릅니다.")
        split_counts = Counter(record.dataset_split for record in records)
        if split_counts[ClaimDatasetSplit.TRAINING] != manifest.training_document_count:
            self._raise_manifest_mismatch("training document 건수가 manifest와 다릅니다.")
        if split_counts[ClaimDatasetSplit.VALIDATION] != manifest.validation_document_count:
            self._raise_manifest_mismatch("validation document 건수가 manifest와 다릅니다.")

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as input_file:
            while chunk := input_file.read(SHA256_READ_SIZE_BYTES):
                digest.update(chunk)
        return digest.hexdigest()

    def _raise_manifest_mismatch(self, message: str) -> None:
        raise ClaimIngestionError(ClaimIngestionErrorCode.MANIFEST_MISMATCH, message)


class ClaimIngestionService:
    INGESTIBLE_DECISIONS: ClassVar[frozenset[ClaimIngestionDecision]] = frozenset(
        {
            ClaimIngestionDecision.INGESTIBLE_STRUCTURED,
            ClaimIngestionDecision.INGESTIBLE_FREE_TEXT,
        }
    )

    def __init__(
        self,
        session: AsyncSession,
        embedder: TextEmbedder,
        document_repository: ClaimDocumentRepository | None = None,
        chunk_repository: ClaimChunkRepository | None = None,
        ingredient_repository: ClaimChunkIngredientRepository | None = None,
        reader: ClaimIngestionFileReader | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._document_repository = document_repository or ClaimDocumentRepository(session)
        self._chunk_repository = chunk_repository or ClaimChunkRepository(session)
        self._ingredient_repository = ingredient_repository or ClaimChunkIngredientRepository(
            session
        )
        self._reader = reader or ClaimIngestionFileReader()

    async def ingest_jsonl(self, request: ClaimIngestionRequest) -> ClaimIngestionResult:
        payload = self._reader.read(request)
        embedded_count = 0
        for start in range(0, len(payload.records), request.batch_size):
            batch = payload.records[start : start + request.batch_size]
            try:
                embedded_count += await self._ingest_batch(batch)
                await self._session.commit()
            except Exception as exc:
                await self._session.rollback()
                if isinstance(exc, ClaimIngestionError):
                    raise ClaimIngestionError(
                        exc.code,
                        f"batch 시작 위치 {start + 1}에서 실패했습니다: {exc}",
                    ) from exc
                raise ClaimIngestionError(
                    ClaimIngestionErrorCode.BATCH_FAILED,
                    f"batch 시작 위치 {start + 1}에서 실패했습니다: {exc}",
                ) from exc

        return ClaimIngestionResult(
            document_count=len(payload.records),
            statement_count=payload.manifest.ingestible_statement_count,
            embedded_count=embedded_count,
            skipped_statement_count=(
                payload.manifest.statement_count - payload.manifest.ingestible_statement_count
            ),
            annotation_version=payload.manifest.annotation_version,
            embedding_model=LocalEmbeddingModel.BGE_M3.value,
        )

    async def _ingest_batch(self, records: list[ClaimExportRecordInput]) -> int:
        embedding_targets = [
            ClaimEmbeddingTarget(
                source_record_id=record.source_record_id,
                statement=statement,
            )
            for record in records
            for statement in record.statements
            if statement.decision in self.INGESTIBLE_DECISIONS
        ]
        vectors_by_statement = await self._embed(embedding_targets)
        for record in records:
            identity = await self._document_repository.upsert(
                ClaimDocumentUpsert(
                    source_record_id=record.source_record_id,
                    annotation_version=record.annotation_version,
                    schema_version=record.schema_version,
                    dataset_split=record.dataset_split,
                    skin_concerns_raw=record.skin_concerns_raw,
                    production_ready=record.production_ready,
                )
            )
            statements = [
                statement
                for statement in record.statements
                if statement.decision in self.INGESTIBLE_DECISIONS
            ]
            chunks = [
                self._to_chunk_upsert(
                    statement,
                    vectors_by_statement[(record.source_record_id, statement.statement_id)].values,
                )
                for statement in statements
            ]
            chunk_identities = await self._chunk_repository.sync_document(identity.id, chunks)
            chunk_ids = {item.statement_id: item.id for item in chunk_identities}
            if len(chunk_ids) != len(statements):
                raise ClaimIngestionError(
                    ClaimIngestionErrorCode.BATCH_FAILED,
                    f"저장된 chunk 수가 입력과 다릅니다: {record.source_record_id}",
                )
            ingredient_rows = [
                ClaimChunkIngredientUpsert(
                    claim_chunk_id=chunk_ids[statement.statement_id],
                    ingredient_id=ingredient.ingredient_id,
                    raw_name=ingredient.raw_name,
                    matching_status=ingredient.matching_status,
                    role=ingredient.role,
                )
                for statement in statements
                for ingredient in statement.ingredient_refs
            ]
            await self._ingredient_repository.replace_for_chunks(
                list(chunk_ids.values()), ingredient_rows
            )
        return len(embedding_targets)

    async def _embed(
        self, targets: list[ClaimEmbeddingTarget]
    ) -> dict[tuple[str, str], EmbeddingVector]:
        if not targets:
            return {}
        result = await self._embedder.embed(
            EmbeddingRequest(texts=[target.statement.content for target in targets])
        )
        self._validate_embeddings(
            result.model,
            result.vectors,
            [target.statement for target in targets],
        )
        return {
            (target.source_record_id, target.statement.statement_id): vector
            for target, vector in zip(targets, result.vectors, strict=True)
        }

    def _validate_embeddings(
        self,
        model: str,
        vectors: list[EmbeddingVector],
        statements: list[ClaimStatementInput],
    ) -> None:
        if model != LocalEmbeddingModel.BGE_M3.value:
            raise ClaimIngestionError(
                ClaimIngestionErrorCode.INVALID_EMBEDDING,
                f"BGE-M3가 아닌 모델 결과입니다: {model}",
            )
        if len(vectors) != len(statements):
            raise ClaimIngestionError(
                ClaimIngestionErrorCode.INVALID_EMBEDDING,
                f"벡터 수가 입력 수와 다릅니다: vectors={len(vectors)}, statements={len(statements)}",
            )
        dimensions = [
            len(vector.values)
            for vector in vectors
            if len(vector.values) != BGE_M3_EMBEDDING_DIMENSIONS
        ]
        if dimensions:
            raise ClaimIngestionError(
                ClaimIngestionErrorCode.INVALID_EMBEDDING,
                f"1024차원이 아닌 벡터가 있습니다: {dimensions}",
            )

    def _to_chunk_upsert(
        self, statement: ClaimStatementInput, vector: list[float]
    ) -> ClaimChunkUpsert:
        return ClaimChunkUpsert(
            statement_id=statement.statement_id,
            statement_type=statement.statement_type,
            content=statement.content,
            source_spans=[
                ClaimSourceSpanValue(
                    json_path=span.json_path,
                    quote=span.quote,
                    start=span.start,
                    end=span.end,
                )
                for span in statement.source_spans
            ],
            decision=statement.decision,
            priority=statement.priority,
            support_status=statement.support_status,
            embedding=vector,
            embedding_model=LocalEmbeddingModel.BGE_M3.value,
        )


class ClaimIngestionCommand:
    async def run(self, request: ClaimIngestionRequest) -> ClaimIngestionResult:
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
            raise ClaimIngestionError(
                ClaimIngestionErrorCode.INVALID_EMBEDDING_CONFIG,
                "config.yaml의 agent.embedding.provider는 local, model은 BAAI/bge-m3여야 합니다.",
            )
        database = Database(settings.database)
        try:
            async with database.session_factory() as session:
                embedder = TextEmbedderFactory().create(embedding_config)
                return await ClaimIngestionService(session, embedder).ingest_jsonl(request)
        finally:
            await database.dispose()


class ClaimIngestionArgumentParser:
    def create(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="NIA Claim JSONL을 BGE-M3로 임베딩해 DB에 적재합니다.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
        parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
        return parser


class ClaimIngestionEntryPoint:
    def run(self, argv: Sequence[str] | None = None) -> int:
        self._configure_stdout()
        arguments = ClaimIngestionArgumentParser().create().parse_args(argv)
        result = asyncio.run(
            ClaimIngestionCommand().run(
                ClaimIngestionRequest(
                    input_path=arguments.input,
                    manifest_path=arguments.manifest,
                    batch_size=arguments.batch_size,
                )
            )
        )
        self._print_result(result)
        return 0

    def _configure_stdout(self) -> None:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def _print_result(self, result: ClaimIngestionResult) -> None:
        print("NIA Claim DB 적재 완료")
        print(f"- document: {result.document_count:,}건")
        print(f"- 적재 statement: {result.statement_count:,}건")
        print(f"- 제외 statement: {result.skipped_statement_count:,}건")
        print(f"- 임베딩 실행: {result.embedded_count:,}건")
        print(f"- annotation_version: {result.annotation_version}")
        print(f"- embedding_model: {result.embedding_model}")


if __name__ == "__main__":
    raise SystemExit(ClaimIngestionEntryPoint().run())
