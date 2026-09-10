"""`Evidence`/`IngredientKnowledgeFact`/NIA Q&A를 읽어 `rag_chunk`에 적재하는 배치 진입점.

`data/scripts/`에 두지 않는 이유: 이 파이프라인은 `agent/rag`(로더·청킹·임베딩)와
`backend/repositories`(저장) 둘 다 필요한데, STRUCTURE.md 규칙상 `data/scripts/`는 `agent`,
`backend`를 import할 수 없다. `backend/services/`는 이미 그 규칙에서 `agent`와 `repositories`
양쪽을 부를 수 있는 계층이라 여기에 둔다.

모든 `sync_*` 메서드는 재실행해도 안전하다(`RagChunkRepository.sync_documents` 참고) -
같은 소스를 다시 적재해도 청크가 중복되지 않고, 원본에서 사라진 필드의 청크는 삭제되고,
바뀌지 않은 청크는 그대로 둔다.

사용법:
    uv run python -m backend.services.rag_ingestion_service --nia-qa-zip "data/nia_qa/*.zip"
"""

import argparse
import asyncio
import glob
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.embedding.openai_embedder import OpenAiEmbedder
from agent.rag.loaders.evidence_loader import EvidenceLoader
from agent.rag.loaders.knowledge_fact_loader import IngredientKnowledgeFactLoader
from agent.rag.loaders.nia_qa_loader import NiaQaLoader
from agent.rag.pipeline import RagIngestionPipeline
from agent.rag.schemas import EmbeddedChunk
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.ingredient_knowledge_fact_repository import (
    IngredientKnowledgeFactRepository,
)
from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from backend.repositories.rag_chunk_repository import (
    RagChunkInsert,
    RagChunkRepository,
    RagSyncResult,
)
from core.config import settings
from core.database import Database
from data.scripts.evidence_schemas import MfdsImportSummary, MfdsRestrictedIngredientItem
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.mfds_client import MfdsRestrictedIngredientClient
from data.scripts.mfds_importer import MfdsRestrictedIngredientImporter
from models.evidence import Evidence, EvidenceSourceType
from models.rag_chunk import RagSourceTable


class RagIngestionService:
    """소스 3종을 전부 `rag_chunk`로 안전하게(재적재해도 중복 없이) 동기화한다. commit은 호출부가 한다."""

    def __init__(self, session: AsyncSession, embedder: OpenAiEmbedder) -> None:
        self._session = session
        self._pipeline = RagIngestionPipeline(FieldChunker(), embedder)
        self._evidence_repository = EvidenceRepository(session)
        self._knowledge_fact_repository = IngredientKnowledgeFactRepository(session)
        self._rag_chunk_repository = RagChunkRepository(session)

    async def sync_evidence(self) -> RagSyncResult:
        rows = await self._evidence_repository.list_all()
        documents = EvidenceLoader().load(rows)
        embedded = self._pipeline.run(documents)
        inserts = self._to_inserts(embedded)
        fetched_refs = [str(row.id) for row in rows]
        return await self._rag_chunk_repository.sync_documents(
            RagSourceTable.EVIDENCE, fetched_refs, inserts
        )

    async def sync_knowledge_facts(self) -> RagSyncResult:
        rows = await self._knowledge_fact_repository.list_all()
        documents = IngredientKnowledgeFactLoader().load(rows)
        embedded = self._pipeline.run(documents)
        inserts = self._to_inserts(embedded)
        fetched_refs = [str(row.id) for row in rows]
        return await self._rag_chunk_repository.sync_documents(
            RagSourceTable.INGREDIENT_KNOWLEDGE_FACT, fetched_refs, inserts
        )

    async def sync_nia_qa(self, zip_paths: list[Path]) -> RagSyncResult:
        documents = NiaQaLoader().load(zip_paths)
        embedded = self._pipeline.run(documents)
        inserts = self._to_inserts(embedded)
        fetched_refs = [document.nia_record_id for document in documents if document.nia_record_id]
        return await self._rag_chunk_repository.sync_documents(
            RagSourceTable.NIA_QA, fetched_refs, inserts
        )

    async def replace_mfds_evidence_and_reindex(
        self,
        items: list[MfdsRestrictedIngredientItem],
        matcher: IngredientNameMatcher,
        review_queue_path: Path,
    ) -> tuple[MfdsImportSummary, int]:
        """MFDS `Evidence` 전량 교체와 그 RAG 재적재를 하나의 트랜잭션으로 확정한다.

        두 단계(Evidence 교체 → RAG 재적재)를 순서대로 따로 실행하면, Evidence 삭제가
        먼저 커밋된 뒤 임베딩이 실패할 경우 검색 데이터가 사라진 채 복구되지 않는다. 그래서
        새 Evidence와 그 임베딩까지 **전부 메모리에서 준비를 끝낸 뒤에만** DB 쓰기(옛 Evidence
        삭제 + 새 Evidence/청크 삽입)를 시작한다 - DB 쓰기 단계에서 실패해도 호출부가 commit을
        안 하면 옛 데이터가 삭제 이전 상태로 롤백된다.
        """
        importer = MfdsRestrictedIngredientImporter(self._session, matcher, review_queue_path)
        rows_to_insert, review_entries = importer.build_new_rows(items)

        # 아직 세션에 추가하지 않은 transient 객체 - EvidenceLoader가 속성만 읽으므로
        # DB에 있든 없든 상관없이 동작한다. id는 build_new_rows가 미리 uuid4()로 채워뒀다.
        pending_evidence = [Evidence(**row) for row in rows_to_insert]
        documents = EvidenceLoader().load(pending_evidence)
        embedded = self._pipeline.run(documents)
        inserts = self._to_inserts(embedded)

        # 여기서부터 DB 쓰기 - 실패하면 호출부가 commit하지 않아 전부 롤백된다.
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

        summary = MfdsImportSummary(
            total_items=len(items),
            inserted=len(rows_to_insert),
            manual_review=len(review_entries),
        )
        return summary, len(inserts)

    def _to_inserts(self, embedded: list[EmbeddedChunk]) -> list[RagChunkInsert]:
        return [
            RagChunkInsert(
                ingredient_id=chunk.draft.ingredient_id,
                source_table=chunk.draft.source_table,
                evidence_id=chunk.draft.evidence_id,
                ingredient_knowledge_fact_id=chunk.draft.ingredient_knowledge_fact_id,
                nia_record_id=chunk.draft.nia_record_id,
                chunk_field=chunk.draft.chunk_field,
                chunk_index=chunk.draft.chunk_index,
                content=chunk.draft.content,
                embedding=chunk.vector,
                embedding_model=chunk.embedding_model,
                confidence_tier=chunk.draft.metadata.confidence_tier,
                cites_cir=chunk.draft.metadata.cites_cir,
                source_title=chunk.draft.metadata.source_title,
                source_url=chunk.draft.metadata.source_url,
                citation_refs=chunk.draft.metadata.citation_refs,
            )
            for chunk in embedded
        ]


async def _run_mfds_replace(review_queue_path: Path) -> None:
    """MFDS 전량 재수집 -> Evidence 교체 -> RAG 재적재를 한 번에, 한 트랜잭션으로 실행한다.

    "MFDS 재수집하고 나중에 따로 RAG 재적재"처럼 두 명령으로 나눠 실행하지 않는다 -
    그 사이에 죽으면 Evidence는 새로 바뀌었는데 rag_chunk는 옛 내용을 가리키는 상태가 된다.
    """
    if settings.mfds is None:
        raise RuntimeError("config.yaml에 mfds.service_key가 없습니다.")
    if settings.openai is None:
        raise RuntimeError("config.yaml에 openai 블록이 없습니다.")

    client = MfdsRestrictedIngredientClient(settings.mfds)
    try:
        print("MFDS API에서 화장품 사용제한 원료정보를 수집하는 중...")
        items = await client.fetch_all()
    finally:
        await client.close()
    print(f"MFDS API에서 {len(items)}건을 받았습니다.")

    embedder = OpenAiEmbedder(
        api_key=settings.openai.api_key, model=settings.openai.embedding_model
    )
    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            candidates = await IngredientMasterRepository(session).list_all_as_candidates()
            if not candidates:
                raise RuntimeError("IngredientMaster가 비어 있습니다.")
            matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
            service = RagIngestionService(session, embedder)
            summary, chunk_count = await service.replace_mfds_evidence_and_reindex(
                items, matcher, review_queue_path
            )
            await session.commit()
    finally:
        await database.dispose()

    print(
        f"Evidence 교체 완료: 총 {summary.total_items}건 "
        f"(매칭 {summary.inserted}건, 수동 검토 {summary.manual_review}건), RAG 청크 {chunk_count}건"
    )


async def _run(nia_qa_zip_glob: str | None) -> None:
    if settings.openai is None:
        raise RuntimeError(
            "config.yaml에 openai 블록이 없습니다. RAG 적재를 실행하려면 api_key를 채워야 합니다."
        )

    embedder = OpenAiEmbedder(
        api_key=settings.openai.api_key, model=settings.openai.embedding_model
    )
    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            service = RagIngestionService(session, embedder)

            evidence_result = await service.sync_evidence()
            print(f"Evidence 동기화: {evidence_result}")

            knowledge_result = await service.sync_knowledge_facts()
            print(f"IngredientKnowledgeFact 동기화: {knowledge_result}")

            if nia_qa_zip_glob:
                zip_paths = [Path(path) for path in glob.glob(nia_qa_zip_glob)]
                if not zip_paths:
                    raise RuntimeError(f"'{nia_qa_zip_glob}' 패턴에 맞는 zip 파일이 없습니다.")
                nia_result = await service.sync_nia_qa(zip_paths)
                print(f"NIA Q&A 동기화({len(zip_paths)}개 zip): {nia_result}")

            await session.commit()
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--nia-qa-zip",
        default=None,
        help="NIA Q-CoT-A 라벨링데이터 zip 경로 glob 패턴. 생략하면 NIA는 적재하지 않는다.",
    )
    parser.add_argument(
        "--mfds-replace",
        action="store_true",
        help="MFDS 전량 재수집 + Evidence 교체 + RAG 재적재를 한 트랜잭션으로 실행하고 종료한다"
        "(다른 소스는 건드리지 않는다).",
    )
    parser.add_argument(
        "--mfds-review-queue-path",
        type=Path,
        default=Path("data/manual_review/mfds_ingredient_match_queue.csv"),
    )
    args = parser.parse_args()
    if args.mfds_replace:
        asyncio.run(_run_mfds_replace(args.mfds_review_queue_path))
    else:
        asyncio.run(_run(args.nia_qa_zip))


if __name__ == "__main__":
    main()
