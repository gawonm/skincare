import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

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
from backend.repositories.claim_chunk_ingredient_repository import (
    ClaimChunkIngredientRepository,
    ClaimChunkIngredientUpsert,
)
from backend.repositories.claim_chunk_repository import (
    ClaimChunkIdentity,
    ClaimChunkRepository,
    ClaimChunkUpsert,
)
from backend.repositories.claim_document_repository import (
    ClaimDocumentIdentity,
    ClaimDocumentRepository,
    ClaimDocumentUpsert,
)
from backend.services.claim_ingestion_schemas import (
    ClaimExportManifestInput,
    ClaimExportRecordInput,
    ClaimIngestionRequest,
)
from backend.services.claim_ingestion_service import (
    CLAIM_EXPORT_VERSION,
    ClaimIngestionError,
    ClaimIngestionErrorCode,
    ClaimIngestionFileReader,
    ClaimIngestionService,
)
from models.claim_chunk import CLAIM_EMBEDDING_DIMENSION

_DOCUMENT_ID_1 = UUID("10000000-0000-0000-0000-000000000001")
_DOCUMENT_ID_2 = UUID("10000000-0000-0000-0000-000000000002")
_CHUNK_ID = UUID("20000000-0000-0000-0000-000000000001")
_INGREDIENT_ID = UUID("f90ba1bc-346b-4627-a387-8cf3759dbd7b")


class FakeClaimEmbedder(TextEmbedder):
    def __init__(self) -> None:
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self.requests.append(request)
        return EmbeddingResult(
            model=LocalEmbeddingModel.BGE_M3.value,
            vectors=[
                EmbeddingVector(values=[float(index)] * CLAIM_EMBEDDING_DIMENSION)
                for index, _ in enumerate(request.texts, start=1)
            ],
        )


class FakeClaimDocumentRepository(ClaimDocumentRepository):
    def __init__(self) -> None:
        self.upserts: list[ClaimDocumentUpsert] = []

    async def upsert(self, record: ClaimDocumentUpsert) -> ClaimDocumentIdentity:
        self.upserts.append(record)
        document_id = _DOCUMENT_ID_1 if len(self.upserts) == 1 else _DOCUMENT_ID_2
        return ClaimDocumentIdentity(id=document_id, source_record_id=record.source_record_id)


class FakeClaimChunkRepository(ClaimChunkRepository):
    def __init__(self) -> None:
        self.syncs: list[tuple[UUID, list[ClaimChunkUpsert]]] = []

    async def sync_document(
        self, claim_document_id: UUID, records: list[ClaimChunkUpsert]
    ) -> list[ClaimChunkIdentity]:
        self.syncs.append((claim_document_id, records))
        return [
            ClaimChunkIdentity(id=_CHUNK_ID, statement_id=record.statement_id) for record in records
        ]


class FakeClaimIngredientRepository(ClaimChunkIngredientRepository):
    def __init__(self) -> None:
        self.replacements: list[tuple[list[UUID], list[ClaimChunkIngredientUpsert]]] = []

    async def replace_for_chunks(
        self, chunk_ids: list[UUID], records: list[ClaimChunkIngredientUpsert]
    ) -> int:
        self.replacements.append((chunk_ids, records))
        return len(records)


class ClaimIngestionFixture:
    def record(self, record_id: str, decision: str) -> ClaimExportRecordInput:
        return ClaimExportRecordInput.model_validate(
            {
                "source_record_id": record_id,
                "annotation_version": "llm-production-test",
                "schema_version": "1.1",
                "dataset_split": "training",
                "skin_concerns_raw": ["여드름/뾰루지"],
                "production_ready": False,
                "statements": [
                    {
                        "statement_id": f"{record_id}-S001",
                        "statement_type": "ingredient_effect_claim",
                        "content": "성분: 나이아신아마이드 효과: 피지 조절",
                        "source_spans": [
                            {
                                "json_path": "$.info.answer",
                                "quote": "나이아신아마이드",
                                "start": 0,
                                "end": 8,
                            }
                        ],
                        "decision": decision,
                        "priority": "primary",
                        "support_status": "unverified",
                        "ingredient_refs": [
                            {
                                "ingredient_id": str(_INGREDIENT_ID),
                                "raw_name": "Niacinamide",
                                "matching_status": "matched",
                                "role": "unspecified",
                            }
                        ],
                    }
                ],
            }
        )

    def write(self, tmp_path: Path, records: list[ClaimExportRecordInput]) -> ClaimIngestionRequest:
        input_path = tmp_path / "claims.jsonl"
        manifest_path = tmp_path / "claims.manifest.json"
        input_path.write_text(
            "".join(f"{record.model_dump_json()}\n" for record in records),
            encoding="utf-8",
        )
        statements = [statement for record in records for statement in record.statements]
        ingestible_count = sum(
            statement.decision.value.startswith("ingestible_") for statement in statements
        )
        blocked_count = sum(statement.decision.value == "blocked" for statement in statements)
        review_count = sum(statement.decision.value == "human_review" for statement in statements)
        manifest = ClaimExportManifestInput(
            export_version=CLAIM_EXPORT_VERSION,
            annotation_version="llm-production-test",
            document_count=len(records),
            statement_count=len(statements),
            ingestible_statement_count=ingestible_count,
            blocked_statement_count=blocked_count,
            human_review_statement_count=review_count,
            training_document_count=len(records),
            validation_document_count=0,
            output_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
        )
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return ClaimIngestionRequest(
            input_path=input_path,
            manifest_path=manifest_path,
            batch_size=2,
        )


class TestClaimIngestionFileReader:
    def test_manifest와_jsonl을_함께_검증한다(self, tmp_path: Path) -> None:
        fixture = ClaimIngestionFixture()
        request = fixture.write(
            tmp_path,
            [
                fixture.record("CASE-1", "ingestible_structured"),
                fixture.record("CASE-2", "blocked"),
            ],
        )

        payload = ClaimIngestionFileReader().read(request)

        assert len(payload.records) == 2
        assert payload.manifest.ingestible_statement_count == 1

    def test_jsonl이_바뀌면_manifest_hash_오류로_중단한다(self, tmp_path: Path) -> None:
        fixture = ClaimIngestionFixture()
        request = fixture.write(tmp_path, [fixture.record("CASE-1", "ingestible_structured")])
        request.input_path.write_text(
            request.input_path.read_text(encoding="utf-8").replace("피지 조절", "보습"),
            encoding="utf-8",
        )

        with pytest.raises(ClaimIngestionError) as error:
            ClaimIngestionFileReader().read(request)

        assert error.value.code is ClaimIngestionErrorCode.MANIFEST_MISMATCH


class TestClaimIngestionService:
    @pytest.mark.asyncio
    async def test_ingestible만_임베딩하고_blocked는_chunk에서_제외한다(
        self, tmp_path: Path
    ) -> None:
        fixture = ClaimIngestionFixture()
        request = fixture.write(
            tmp_path,
            [
                fixture.record("CASE-1", "ingestible_structured"),
                fixture.record("CASE-2", "blocked"),
            ],
        )
        session = AsyncMock(spec=AsyncSession)
        embedder = FakeClaimEmbedder()
        document_repository = FakeClaimDocumentRepository()
        chunk_repository = FakeClaimChunkRepository()
        ingredient_repository = FakeClaimIngredientRepository()
        service = ClaimIngestionService(
            cast(AsyncSession, session),
            embedder,
            document_repository=document_repository,
            chunk_repository=chunk_repository,
            ingredient_repository=ingredient_repository,
        )

        result = await service.ingest_jsonl(request)

        assert result.document_count == 2
        assert result.statement_count == 1
        assert result.embedded_count == 1
        assert result.skipped_statement_count == 1
        assert embedder.requests[0].texts == ["성분: 나이아신아마이드 효과: 피지 조절"]
        assert len(document_repository.upserts) == 2
        assert len(chunk_repository.syncs[0][1]) == 1
        assert chunk_repository.syncs[1][1] == []
        assert ingredient_repository.replacements[0][1][0].ingredient_id == _INGREDIENT_ID
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()


class TestClaimRepositories:
    @pytest.mark.asyncio
    async def test_document_upsert는_승인된_자연키를_사용한다(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value = SimpleNamespace(
            one=lambda: SimpleNamespace(id=_DOCUMENT_ID_1, source_record_id="CASE-1")
        )
        repository = ClaimDocumentRepository(cast(AsyncSession, session))

        identity = await repository.upsert(
            ClaimDocumentUpsert.model_validate(
                {
                    "source_record_id": "CASE-1",
                    "annotation_version": "llm-production-test",
                    "schema_version": "1.1",
                    "dataset_split": "training",
                    "skin_concerns_raw": ["모공"],
                    "production_ready": False,
                }
            )
        )

        statement = session.execute.await_args.args[0]
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        assert identity.id == _DOCUMENT_ID_1
        assert "ON CONFLICT ON CONSTRAINT uq_claim_document_record_annotation" in compiled

    @pytest.mark.asyncio
    async def test_chunk_sync는_문서별_기존_목록을_동기화한다(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.execute.side_effect = [
            SimpleNamespace(),
            SimpleNamespace(
                all=lambda: [SimpleNamespace(id=_CHUNK_ID, statement_id="CASE-1-S001")]
            ),
        ]
        repository = ClaimChunkRepository(cast(AsyncSession, session))
        record = ClaimChunkUpsert.model_validate(
            {
                "statement_id": "CASE-1-S001",
                "statement_type": "ingredient_effect_claim",
                "content": "성분: 나이아신아마이드 효과: 피지 조절",
                "source_spans": [
                    {
                        "json_path": "$.info.answer",
                        "quote": "나이아신아마이드",
                        "start": 0,
                        "end": 8,
                    }
                ],
                "decision": "ingestible_structured",
                "priority": "primary",
                "support_status": "unverified",
                "embedding": [0.0] * CLAIM_EMBEDDING_DIMENSION,
                "embedding_model": LocalEmbeddingModel.BGE_M3.value,
            }
        )

        identities = await repository.sync_document(_DOCUMENT_ID_1, [record])

        delete_statement = session.execute.await_args_list[0].args[0]
        upsert_statement = session.execute.await_args_list[1].args[0]
        compiled_delete = str(delete_statement.compile(dialect=postgresql.dialect()))
        compiled_upsert = str(upsert_statement.compile(dialect=postgresql.dialect()))
        assert identities[0].id == _CHUNK_ID
        assert "DELETE FROM claim_chunk" in compiled_delete
        assert "ON CONFLICT ON CONSTRAINT uq_claim_chunk_document_statement" in compiled_upsert

    @pytest.mark.asyncio
    async def test_ingredient_replace는_기존_연결을_지우고_현재_연결을_넣는다(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        repository = ClaimChunkIngredientRepository(cast(AsyncSession, session))
        record = ClaimChunkIngredientUpsert.model_validate(
            {
                "claim_chunk_id": str(_CHUNK_ID),
                "ingredient_id": str(_INGREDIENT_ID),
                "raw_name": "Niacinamide",
                "matching_status": "matched",
                "role": "unspecified",
            }
        )

        count = await repository.replace_for_chunks([_CHUNK_ID], [record])

        delete_statement = session.execute.await_args_list[0].args[0]
        insert_statement = session.execute.await_args_list[1].args[0]
        assert count == 1
        assert "DELETE FROM claim_chunk_ingredient" in str(
            delete_statement.compile(dialect=postgresql.dialect())
        )
        assert "INSERT INTO claim_chunk_ingredient" in str(
            insert_statement.compile(dialect=postgresql.dialect())
        )
