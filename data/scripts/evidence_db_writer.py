"""`FINAL_EVIDENCE_DB_ACTION_PLAN`을 실제 `evidence_document`/`evidence_chunk`/
`evidence_chunk_ingredient`에 반영하는 write 진입점.

단일 트랜잭션으로 전부 적용한다 - 마지막에 딱 한 번만 commit하고, 도중에 예외가
나면 그 세션은 commit되지 않은 채로 버려진다(rollback). REUSE/DEFER 대상은 아무
것도 건드리지 않는다. document REMOVE는 `ON DELETE CASCADE`로 그 document의
chunk/link까지 자동 정리되므로, 링크만 단독으로 빼는 PMID 30945430(Panthenol)
한 건만 별도 DELETE로 처리한다.

사용법:
    uv run python -m data.scripts.evidence_db_writer --dsn postgresql+asyncpg://app:app@localhost:5432/evidence_v5_write
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Database, DatabaseConfig
from data.scripts.evidence_db_writer_schemas import (
    BundleChunkRecord,
    BundleDocumentRecord,
    WriteTransactionSummary,
)
from models.evidence_chunk import EvidenceChunk, evidence_chunk_ingredient
from models.evidence_document import EvidenceDocument, EvidenceDocumentSourceType

_DEFAULT_DOCUMENTS_BUNDLE = Path("data/outputs/evidence_coverage/combined_evidence_documents.jsonl")
_DEFAULT_CHUNKS_BUNDLE = Path("data/outputs/evidence_coverage/combined_evidence_chunks.jsonl")
_DEFAULT_VECTORS_PATH = Path("data/outputs/evidence_coverage/embeddings/evidence_embeddings.jsonl")
_DEFAULT_DOCUMENTS_PLAN = Path("data/outputs/evidence_coverage/evidence_db_load_plan_documents.csv")
_DEFAULT_CHUNKS_PLAN = Path("data/outputs/evidence_coverage/evidence_db_load_plan_chunks.csv")
_DEFAULT_LINKS_PLAN = Path("data/outputs/evidence_coverage/evidence_db_load_plan_links.csv")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class EvidenceBundleDbWriter:
    """FINAL_EVIDENCE_DB_ACTION_PLAN 한 세트를 하나의 세션/트랜잭션 안에서 적용한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_documents(
        self, records: list[BundleDocumentRecord]
    ) -> dict[tuple[str, str], UUID]:
        source_id_to_pk: dict[tuple[str, str], UUID] = {}
        for record in records:
            document = EvidenceDocument(
                source_id=record.source_id,
                source_type=record.source_type,
                source_title=record.source_title,
                publisher=record.publisher,
                document_date=record.document_date,
                url=record.url,
                doi=record.doi,
                pmid=record.pmid,
                jurisdiction=None,
                language=record.language,
                evidence_level=record.evidence_level,
                raw_ingredient_names=record.raw_ingredient_names,
                document_status=record.document_status,
                study_type=record.study_type,
                formulation_type=record.formulation_type,
                claim_topics=[topic.value for topic in record.claim_topics],
                retrieved_at=record.retrieved_at,
            )
            self._session.add(document)
            await self._session.flush()
            source_id_to_pk[(record.source_type.value, record.source_id)] = document.id
        return source_id_to_pk

    async def insert_chunks(
        self,
        records: list[BundleChunkRecord],
        *,
        document_id_by_source: dict[tuple[str, str], UUID],
        embedding_by_chunk_id: dict[str, list[float]],
        embedding_model: str,
    ) -> dict[str, UUID]:
        chunk_id_to_pk: dict[str, UUID] = {}
        for record in records:
            document_id = document_id_by_source[
                (record.source_type.value, record.document_source_id)
            ]
            chunk = EvidenceChunk(
                document_id=document_id,
                chunk_id=record.chunk_id,
                source_type=record.source_type,
                source_title=record.source_title,
                page=record.page,
                section=record.section,
                chunk_index=record.chunk_index,
                content=record.content,
                content_hash=record.content_hash,
                parser_version=record.parser_version,
                embedding=embedding_by_chunk_id[record.chunk_id],
                embedding_model=embedding_model,
                url=record.url,
                doi=record.doi,
                pmid=record.pmid,
                jurisdiction=None,
                evidence_level=record.evidence_level,
            )
            self._session.add(chunk)
            await self._session.flush()
            chunk_id_to_pk[record.chunk_id] = chunk.id
        return chunk_id_to_pk

    async def replace_chunk(
        self,
        record: BundleChunkRecord,
        *,
        embedding: list[float],
        embedding_model: str,
        new_document_title: str,
    ) -> None:
        chunk = (
            await self._session.execute(
                select(EvidenceChunk).where(EvidenceChunk.chunk_id == record.chunk_id)
            )
        ).scalar_one()
        chunk.content = record.content
        chunk.content_hash = record.content_hash
        chunk.parser_version = record.parser_version
        chunk.embedding = embedding
        chunk.embedding_model = embedding_model

        document = (
            await self._session.execute(
                select(EvidenceDocument).where(EvidenceDocument.id == chunk.document_id)
            )
        ).scalar_one()
        document.source_title = new_document_title

    async def insert_links(
        self, actions: list[tuple[str, UUID]], *, chunk_id_to_pk: dict[str, UUID]
    ) -> int:
        count = 0
        for chunk_id, ingredient_id in actions:
            await self._session.execute(
                evidence_chunk_ingredient.insert().values(
                    evidence_chunk_id=chunk_id_to_pk[chunk_id], ingredient_id=ingredient_id
                )
            )
            count += 1
        return count

    async def resolve_existing_chunk_ids(self, chunk_ids: set[str]) -> dict[str, UUID]:
        """CIR reuse link처럼 이번 트랜잭션에서 새로 만들지 않는 기존 chunk의 PK를 찾는다."""
        if not chunk_ids:
            return {}
        rows = (
            await self._session.execute(
                select(EvidenceChunk.chunk_id, EvidenceChunk.id).where(
                    EvidenceChunk.chunk_id.in_(chunk_ids)
                )
            )
        ).all()
        return {chunk_id: pk for chunk_id, pk in rows}

    async def remove_standalone_link(self, chunk_id: str, ingredient_id: UUID) -> int:
        chunk_pk = (
            await self._session.execute(
                select(EvidenceChunk.id).where(EvidenceChunk.chunk_id == chunk_id)
            )
        ).scalar_one()
        result = await self._session.execute(
            delete(evidence_chunk_ingredient).where(
                evidence_chunk_ingredient.c.evidence_chunk_id == chunk_pk,
                evidence_chunk_ingredient.c.ingredient_id == ingredient_id,
            )
        )
        return result.rowcount or 0

    async def remove_documents(self, source_ids: list[str]) -> int:
        result = await self._session.execute(
            delete(EvidenceDocument).where(
                EvidenceDocument.source_type == EvidenceDocumentSourceType.PUBMED_ABSTRACT,
                EvidenceDocument.source_id.in_(source_ids),
            )
        )
        return result.rowcount or 0


def _build_document_records(
    bundle_documents: list[dict[str, object]], insert_source_ids: set[str]
) -> list[BundleDocumentRecord]:
    return [
        BundleDocumentRecord.model_validate(d)
        for d in bundle_documents
        if d["source_id"] in insert_source_ids
    ]


def _build_chunk_records(
    bundle_chunks: list[dict[str, object]], chunk_ids: set[str]
) -> list[BundleChunkRecord]:
    by_id = {c["chunk_id"]: BundleChunkRecord.model_validate(c) for c in bundle_chunks}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


async def _run(
    *,
    dsn: str,
    documents_bundle_path: Path,
    chunks_bundle_path: Path,
    vectors_path: Path,
    documents_plan_path: Path,
    chunks_plan_path: Path,
    links_plan_path: Path,
) -> WriteTransactionSummary:
    documents_plan = _read_csv(documents_plan_path)
    chunks_plan = _read_csv(chunks_plan_path)
    links_plan = _read_csv(links_plan_path)
    bundle_documents = _read_jsonl(documents_bundle_path)
    bundle_chunks = _read_jsonl(chunks_bundle_path)
    vectors = {v["chunk_id"]: v for v in _read_jsonl(vectors_path)}

    insert_doc_source_ids = {r["source_id"] for r in documents_plan if r["action"] == "INSERT"}
    remove_doc_pmids = [
        r["key"]
        for r in documents_plan
        if r["action"] == "REMOVE" and r["source_type"] == "pubmed_abstract"
    ]
    remove_doc_source_ids = [f"PMID:{pmid}" for pmid in remove_doc_pmids]

    insert_chunk_ids = {r["chunk_id"] for r in chunks_plan if r["action"] == "INSERT"}
    replace_chunk_ids = [r["chunk_id"] for r in chunks_plan if r["action"] == "REPLACE"]

    insert_links = [
        (r["chunk_id"], UUID(r["ingredient_id"])) for r in links_plan if r["action"] == "INSERT"
    ]
    # 링크 단독 제거는 REMOVE 대상 document에 속하지 않는 것만 처리한다 - 그 document에 딸린
    # 링크는 document REMOVE의 ON DELETE CASCADE가 이미 정리한다.
    standalone_remove_links = [
        (r["chunk_id"], UUID(r["ingredient_id"]))
        for r in links_plan
        if r["action"] == "REMOVE"
        and not any(r["chunk_id"].startswith(f"PMID:{pmid}:") for pmid in remove_doc_pmids)
    ]

    document_records = _build_document_records(bundle_documents, insert_doc_source_ids)
    insert_chunk_records = _build_chunk_records(bundle_chunks, insert_chunk_ids)
    replace_chunk_records = _build_chunk_records(bundle_chunks, set(replace_chunk_ids))

    database = Database(DatabaseConfig(url=dsn))
    try:
        async with database.session_factory() as session:
            writer = EvidenceBundleDbWriter(session)
            try:
                document_id_by_source = await writer.insert_documents(document_records)

                embedding_model = (
                    next(iter(vectors.values()))["model"] if vectors else "BAAI/bge-m3"
                )
                embedding_by_chunk_id = {chunk_id: v["vector"] for chunk_id, v in vectors.items()}

                chunk_id_to_pk = await writer.insert_chunks(
                    insert_chunk_records,
                    document_id_by_source=document_id_by_source,
                    embedding_by_chunk_id=embedding_by_chunk_id,
                    embedding_model=embedding_model,
                )

                for record in replace_chunk_records:
                    bundle_doc = next(
                        d
                        for d in bundle_documents
                        if d["source_type"] == record.source_type.value
                        and d["source_id"] == record.document_source_id
                    )
                    await writer.replace_chunk(
                        record,
                        embedding=embedding_by_chunk_id[record.chunk_id],
                        embedding_model=embedding_model,
                        new_document_title=bundle_doc["source_title"],
                    )

                reuse_chunk_ids = {
                    chunk_id for chunk_id, _ in insert_links if chunk_id not in chunk_id_to_pk
                }
                chunk_id_to_pk.update(await writer.resolve_existing_chunk_ids(reuse_chunk_ids))

                links_inserted = await writer.insert_links(
                    insert_links, chunk_id_to_pk=chunk_id_to_pk
                )

                links_removed = 0
                for chunk_id, ingredient_id in standalone_remove_links:
                    links_removed += await writer.remove_standalone_link(chunk_id, ingredient_id)

                documents_removed = await writer.remove_documents(remove_doc_source_ids)

                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await database.dispose()

    return WriteTransactionSummary(
        documents_inserted=len(document_records),
        documents_removed=documents_removed,
        chunks_inserted=len(insert_chunk_records),
        chunks_replaced=len(replace_chunk_records),
        chunks_removed=documents_removed,  # cascade: document REMOVE 1건당 chunk 1건
        links_inserted=links_inserted,
        links_removed=links_removed + documents_removed,  # cascade 링크 + 단독 링크
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="asyncpg DSN(postgresql+asyncpg://...)")
    parser.add_argument("--documents-bundle-path", type=Path, default=_DEFAULT_DOCUMENTS_BUNDLE)
    parser.add_argument("--chunks-bundle-path", type=Path, default=_DEFAULT_CHUNKS_BUNDLE)
    parser.add_argument("--vectors-path", type=Path, default=_DEFAULT_VECTORS_PATH)
    parser.add_argument("--documents-plan-path", type=Path, default=_DEFAULT_DOCUMENTS_PLAN)
    parser.add_argument("--chunks-plan-path", type=Path, default=_DEFAULT_CHUNKS_PLAN)
    parser.add_argument("--links-plan-path", type=Path, default=_DEFAULT_LINKS_PLAN)
    args = parser.parse_args()

    summary = asyncio.run(
        _run(
            dsn=args.dsn,
            documents_bundle_path=args.documents_bundle_path,
            chunks_bundle_path=args.chunks_bundle_path,
            vectors_path=args.vectors_path,
            documents_plan_path=args.documents_plan_path,
            chunks_plan_path=args.chunks_plan_path,
            links_plan_path=args.links_plan_path,
        )
    )
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
