"""근거 원본을 현재 Agent DTO로 변환해 설정에서 선택한 임베딩 청크로 적재한다."""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.pipeline import RagIngestionPipeline
from agent.rag.ports import TextEmbedder
from agent.rag.schemas import (
    EmbeddedChunk,
    EvidenceRecord,
)
from agent.rag.schemas import (
    EvidenceSourceType as AgentEvidenceSourceType,
)
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.ingredient_knowledge_fact_repository import (
    IngredientKnowledgeFactRepository,
)
from backend.repositories.rag_chunk_repository import (
    RagChunkInsert,
    RagChunkRepository,
    RagSyncResult,
)
from backend.services.rag_document_mapper import RagDocumentMapper
from data.scripts.evidence_schemas import MfdsImportSummary, MfdsRestrictedIngredientItem
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.mfds_importer import MfdsRestrictedIngredientImporter
from models.evidence import Evidence, EvidenceSourceType
from models.rag_chunk import RagChunkField, RagConfidenceTier, RagSourceTable


class MfdsReplaceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: MfdsImportSummary
    chunk_count: int


class RagInsertSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_table: RagSourceTable
    evidence_id: UUID | None = None
    ingredient_knowledge_fact_id: UUID | None = None


class RagIngestionService:
    """DB 트랜잭션은 호출자에게 남기고 현재 Agent 청킹·임베딩 계약만 호출한다."""

    def __init__(self, session: AsyncSession, embedder: TextEmbedder) -> None:
        self._session = session
        self._documents = RagDocumentMapper()
        self._pipeline = RagIngestionPipeline(FieldChunker(), embedder)
        self._evidence_repository = EvidenceRepository(session)
        self._knowledge_fact_repository = IngredientKnowledgeFactRepository(session)
        self._rag_chunk_repository = RagChunkRepository(session)

    async def sync_evidence(self) -> RagSyncResult:
        rows = await self._evidence_repository.list_all()
        embedded = await self._pipeline.run(self._documents.evidence(rows))
        return await self._rag_chunk_repository.sync_documents(
            RagSourceTable.EVIDENCE,
            [str(row.id) for row in rows],
            self._to_inserts(embedded),
        )

    async def sync_knowledge_facts(self) -> RagSyncResult:
        rows = await self._knowledge_fact_repository.list_all()
        embedded = await self._pipeline.run(self._documents.knowledge(rows))
        return await self._rag_chunk_repository.sync_documents(
            RagSourceTable.INGREDIENT_KNOWLEDGE_FACT,
            [str(row.id) for row in rows],
            self._to_inserts(embedded),
        )

    async def replace_mfds_evidence_and_reindex(
        self,
        items: list[MfdsRestrictedIngredientItem],
        matcher: IngredientNameMatcher,
        review_queue_path: Path,
    ) -> MfdsReplaceResult:
        """새 Evidence와 임베딩 준비가 끝난 뒤에만 기존 데이터를 교체한다."""
        importer = MfdsRestrictedIngredientImporter(self._session, matcher, review_queue_path)
        rows_to_insert, review_entries = importer.build_new_rows(items)
        collected_at = datetime.now(UTC)
        # 서버 기본값은 INSERT 뒤에 생기므로 임베딩용 DTO를 먼저 만들 때도 같은 수집 시각을 넣는다.
        pending_evidence = [Evidence(**row, collected_at=collected_at) for row in rows_to_insert]
        embedded = await self._pipeline.run(self._documents.evidence(pending_evidence))
        inserts = self._to_inserts(embedded)

        # 임베딩까지 성공한 뒤 DB를 바꿔야 실패 시 호출자가 기존 상태로 롤백할 수 있다.
        await self._session.execute(
            delete(Evidence).where(
                Evidence.source_type == EvidenceSourceType.MFDS_RESTRICTED_INGREDIENT
            )
        )
        if pending_evidence:
            self._session.add_all(pending_evidence)
        if inserts:
            await self._rag_chunk_repository.save_many(inserts)
        importer.write_review_queue(review_entries)
        return MfdsReplaceResult(
            summary=MfdsImportSummary(
                total_items=len(items),
                inserted=len(rows_to_insert),
                manual_review=len(review_entries),
            ),
            chunk_count=len(inserts),
        )

    def _to_inserts(self, embedded: list[EmbeddedChunk]) -> list[RagChunkInsert]:
        return [self._to_insert(chunk) for chunk in embedded]

    def _to_insert(self, chunk: EmbeddedChunk) -> RagChunkInsert:
        evidence = chunk.draft.evidence
        source = self._source(evidence)
        return RagChunkInsert(
            ingredient_id=self._ingredient_id(evidence),
            source_table=source.source_table,
            evidence_id=source.evidence_id,
            ingredient_knowledge_fact_id=source.ingredient_knowledge_fact_id,
            nia_record_id=None,
            chunk_field=RagChunkField(chunk.draft.field_id),
            chunk_index=0,
            content=chunk.draft.content,
            embedding=list(chunk.vector.values),
            embedding_model=chunk.embedding_model,
            confidence_tier=RagConfidenceTier(chunk.draft.confidence_tier.value),
            cites_cir=bool(
                evidence.source_reference and "CIR" in evidence.source_reference.upper()
            ),
            source_title=evidence.source_title,
            source_url=evidence.url,
            citation_refs=[evidence.source_reference] if evidence.source_reference else [],
        )

    def _source(self, evidence: EvidenceRecord) -> RagInsertSource:
        source_id = UUID(evidence.evidence_id)
        if evidence.source_type is AgentEvidenceSourceType.MFDS:
            return RagInsertSource(source_table=RagSourceTable.EVIDENCE, evidence_id=source_id)
        if evidence.source_type is AgentEvidenceSourceType.INGREDIENT_KNOWLEDGE:
            return RagInsertSource(
                source_table=RagSourceTable.INGREDIENT_KNOWLEDGE_FACT,
                ingredient_knowledge_fact_id=source_id,
            )
        raise ValueError(f"현재 DB 적재가 지원하지 않는 근거 출처입니다: {evidence.source_type}")

    def _ingredient_id(self, evidence: EvidenceRecord) -> UUID:
        if len(evidence.target_ids) != 1:
            raise ValueError("현재 성분 RAG 청크는 정확히 하나의 성분 ID가 필요합니다.")
        return UUID(evidence.target_ids[0])


class RagIngestionCommand:
    """CLI에서도 애플리케이션과 같은 config.yaml 임베딩 설정을 사용한다."""

    async def run(self, replace_mfds: bool, review_queue_path: Path) -> None:
        # 단위 테스트가 CLI용 config.yaml 유무에 종속되지 않도록 실행 시점에만 설정을 읽는다.
        from agent.rag.embedding.factory import TextEmbedderFactory
        from backend.services.agent_configuration import AgentConfigurationAssembler
        from core.config import settings

        embedder = TextEmbedderFactory().create(
            AgentConfigurationAssembler().create_embedding(settings.openai, settings.agent)
        )
        if replace_mfds:
            await self._replace_mfds(embedder, review_queue_path)
            return
        await self._sync(embedder)

    async def _replace_mfds(self, embedder: TextEmbedder, review_queue_path: Path) -> None:
        from backend.repositories.ingredient_master_repository import IngredientMasterRepository
        from core.config import settings
        from core.database import Database
        from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
        from data.scripts.mfds_client import MfdsRestrictedIngredientClient

        if settings.mfds is None:
            raise RuntimeError("config.yaml에 mfds.service_key가 없습니다.")
        client = MfdsRestrictedIngredientClient(settings.mfds)
        try:
            items = await client.fetch_all()
        finally:
            await client.close()
        database = Database(settings.database)
        try:
            async with database.session_factory() as session:
                candidates = await IngredientMasterRepository(session).list_all_as_candidates()
                if not candidates:
                    raise RuntimeError("IngredientMaster가 비어 있습니다.")
                matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
                result = await RagIngestionService(
                    session, embedder
                ).replace_mfds_evidence_and_reindex(items, matcher, review_queue_path)
                await session.commit()
        finally:
            await database.dispose()
        print(
            f"Evidence 교체 완료: 총 {result.summary.total_items}건 "
            f"(매칭 {result.summary.inserted}건, 수동 검토 {result.summary.manual_review}건), "
            f"RAG 청크 {result.chunk_count}건"
        )

    async def _sync(self, embedder: TextEmbedder) -> None:
        from core.config import settings
        from core.database import Database

        database = Database(settings.database)
        try:
            async with database.session_factory() as session:
                service = RagIngestionService(session, embedder)
                evidence = await service.sync_evidence()
                knowledge = await service.sync_knowledge_facts()
                await session.commit()
        finally:
            await database.dispose()
        print(f"Evidence 동기화: {evidence}")
        print(f"IngredientKnowledgeFact 동기화: {knowledge}")


class RagIngestionArgumentParser:
    def create(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument(
            "--mfds-replace",
            action="store_true",
            help="MFDS 전량 재수집과 RAG 재적재를 한 트랜잭션으로 실행합니다.",
        )
        parser.add_argument(
            "--mfds-review-queue-path",
            type=Path,
            default=Path("data/manual_review/mfds_ingredient_match_queue.csv"),
        )
        return parser


class RagIngestionEntryPoint:
    def run(self) -> None:
        args = RagIngestionArgumentParser().create().parse_args()
        asyncio.run(RagIngestionCommand().run(args.mfds_replace, args.mfds_review_queue_path))


if __name__ == "__main__":
    RagIngestionEntryPoint().run()
