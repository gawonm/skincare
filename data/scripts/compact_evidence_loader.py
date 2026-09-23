"""compact Evidence collector 가 만든 `EvidenceBundle` JSONL 을 BGE-M3 로 임베딩해 적재한다.

`evidence_document`(get-or-create) → `evidence_chunk`(chunk_id 기준 건너뛰기) →
`evidence_chunk_ingredient`(없는 링크만 추가). 재실행해도 중복 삽입되지 않는다.
기본은 dry-run 이며 `--execute` 를 줘야 임베딩 모델을 로드하고 DB 에 쓴다.
이미 DB 에 있는 document/chunk 는 덮어쓰지 않는다(MFDS 8,288건과 기존 시범 PubMed 3건 보호).
임베더는 기존 `MfdsEvidenceEmbedder`(BAAI/bge-m3, 1024차원)를 그대로 쓴다.

사용법:
    uv run python -m data.scripts.compact_evidence_loader             # dry-run
    uv run python -m data.scripts.compact_evidence_loader --execute   # 실제 적재
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import Database, DatabaseConfig
from data.scripts.evidence_collector_schemas import EvidenceBundle, EvidenceChunkDraft
from data.scripts.mfds_evidence_embedder import MfdsEvidenceEmbedder
from models.evidence_chunk import EvidenceChunk, evidence_chunk_ingredient
from models.evidence_document import EvidenceDocument, EvidenceDocumentSourceType

_DEFAULT_BUNDLES_PATH = Path("data/processed/compact_evidence_bundles.jsonl")
_JSON_INDENT = 2


class CompactEvidenceLoadSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    dry_run: bool
    bundles: int
    documents_inserted: int
    documents_already_existed: int
    chunks_planned: int
    chunks_inserted: int
    chunks_already_existed: int
    chunk_hash_mismatches: list[str]
    links_inserted: int
    embedding_model: str | None


class CompactEvidenceLoader:
    def __init__(self, session: AsyncSession, embedder: MfdsEvidenceEmbedder | None) -> None:
        self._session = session
        self._embedder = embedder

    async def load(
        self, bundles: list[EvidenceBundle], *, dry_run: bool
    ) -> CompactEvidenceLoadSummary:
        document_ids: dict[str, UUID] = {}
        documents_inserted = 0
        for bundle in bundles:
            document = bundle.document
            existing_id = await self._find_document_id(document.source_type, document.source_id)
            if existing_id is not None:
                document_ids[document.source_id] = existing_id
                continue
            documents_inserted += 1
            if dry_run:
                continue
            row = EvidenceDocument(
                source_id=document.source_id,
                source_type=document.source_type,
                source_title=document.source_title,
                publisher=document.publisher,
                document_date=document.document_date,
                url=document.url,
                doi=document.doi,
                pmid=document.pmid,
                jurisdiction=None,
                language=document.language,
                evidence_level=document.evidence_level,
                raw_ingredient_names=document.raw_ingredient_names,
                document_status=document.document_status,
                study_type=document.study_type,
                formulation_type=document.formulation_type,
                claim_topics=[topic.value for topic in document.claim_topics],
                retrieved_at=document.retrieved_at,
            )
            self._session.add(row)
            await self._session.flush()
            document_ids[document.source_id] = row.id

        all_chunks = [chunk for bundle in bundles for chunk in bundle.chunks]
        existing_chunks = await self._existing_chunks([c.chunk_id for c in all_chunks])
        # 같은 chunk_id 의 원문이 달라졌으면 덮어쓰지 않고 보고한다(규칙 7)
        mismatches = [
            c.chunk_id
            for c in all_chunks
            if c.chunk_id in existing_chunks and existing_chunks[c.chunk_id][1] != c.content_hash
        ]
        pending = [c for c in all_chunks if c.chunk_id not in existing_chunks]

        chunks_inserted = 0
        model_name: str | None = None
        if pending and not dry_run:
            if self._embedder is None:
                raise RuntimeError("--execute 인데 임베더가 없습니다")
            result = await self._embedder.embed_texts([c.content for c in pending])
            model_name = result.model
            for chunk, vector in zip(pending, result.vectors, strict=True):
                await self._insert_chunk(
                    chunk, document_ids[chunk.document_source_id], vector, model_name
                )
                chunks_inserted += 1

        links_inserted = 0
        if not dry_run:
            for chunk in all_chunks:
                chunk_row_id = (
                    existing_chunks[chunk.chunk_id][0]
                    if chunk.chunk_id in existing_chunks
                    else await self._chunk_row_id(chunk.chunk_id)
                )
                for ingredient_id in chunk.ingredient_ids:
                    if await self._insert_link_if_missing(chunk_row_id, ingredient_id):
                        links_inserted += 1
            await self._session.commit()

        return CompactEvidenceLoadSummary(
            dry_run=dry_run,
            bundles=len(bundles),
            documents_inserted=documents_inserted,
            documents_already_existed=len(bundles) - documents_inserted,
            chunks_planned=len(pending),
            chunks_inserted=chunks_inserted,
            chunks_already_existed=len(existing_chunks),
            chunk_hash_mismatches=mismatches,
            links_inserted=links_inserted,
            embedding_model=model_name,
        )

    async def _find_document_id(
        self, source_type: EvidenceDocumentSourceType, source_id: str
    ) -> UUID | None:
        result = await self._session.execute(
            select(EvidenceDocument.id).where(
                EvidenceDocument.source_type == source_type, EvidenceDocument.source_id == source_id
            )
        )
        return result.scalar_one_or_none()

    async def _existing_chunks(self, chunk_ids: list[str]) -> dict[str, tuple[UUID, str]]:
        result = await self._session.execute(
            select(EvidenceChunk.chunk_id, EvidenceChunk.id, EvidenceChunk.content_hash).where(
                EvidenceChunk.chunk_id.in_(chunk_ids)
            )
        )
        return {chunk_id: (row_id, content_hash) for chunk_id, row_id, content_hash in result.all()}

    async def _chunk_row_id(self, chunk_id: str) -> UUID:
        result = await self._session.execute(
            select(EvidenceChunk.id).where(EvidenceChunk.chunk_id == chunk_id)
        )
        return result.scalar_one()

    async def _insert_chunk(
        self, chunk: EvidenceChunkDraft, document_id: UUID, vector: list[float], model: str
    ) -> None:
        self._session.add(
            EvidenceChunk(
                document_id=document_id,
                chunk_id=chunk.chunk_id,
                source_type=chunk.source_type,
                source_title=chunk.source_title,
                page=chunk.page,
                section=chunk.section,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                content_hash=chunk.content_hash,
                parser_version=chunk.parser_version,
                embedding=vector,
                embedding_model=model,
                url=chunk.url,
                doi=chunk.doi,
                pmid=chunk.pmid,
                jurisdiction=None,
                evidence_level=chunk.evidence_level,
            )
        )
        await self._session.flush()

    async def _insert_link_if_missing(self, chunk_row_id: UUID, ingredient_id: UUID) -> bool:
        found = await self._session.execute(
            select(evidence_chunk_ingredient.c.evidence_chunk_id).where(
                evidence_chunk_ingredient.c.evidence_chunk_id == chunk_row_id,
                evidence_chunk_ingredient.c.ingredient_id == ingredient_id,
            )
        )
        if found.first() is not None:
            return False
        await self._session.execute(
            evidence_chunk_ingredient.insert().values(
                evidence_chunk_id=chunk_row_id, ingredient_id=ingredient_id
            )
        )
        return True


async def _run(
    bundles_path: Path,
    *,
    execute: bool,
    dsn: str | None = None,
) -> CompactEvidenceLoadSummary:
    if not bundles_path.exists():
        raise RuntimeError(f"bundle 파일이 없습니다: {bundles_path}")
    bundles = [
        EvidenceBundle.model_validate_json(line)
        for line in bundles_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 새 기준본 후보를 기존 config DB와 분리해 검증할 수 있도록 CLI에서만 DSN 교체를 허용한다.
    database = Database(DatabaseConfig(url=dsn) if dsn is not None else settings.database)
    try:
        async with database.session_factory() as session:
            embedder = MfdsEvidenceEmbedder(settings.agent.embedding) if execute else None
            return await CompactEvidenceLoader(session, embedder).load(bundles, dry_run=not execute)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bundles", type=Path, default=_DEFAULT_BUNDLES_PATH)
    parser.add_argument(
        "--execute", action="store_true", help="임베딩하고 DB 에 쓴다(기본 dry-run)"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="config DB 대신 사용할 SQLAlchemy DSN",
    )
    args = parser.parse_args()
    summary = asyncio.run(_run(args.bundles, execute=args.execute, dsn=args.dsn))
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=_JSON_INDENT))


if __name__ == "__main__":
    main()
