"""`evidence_document`/`evidence_chunk`/`evidence_chunk_ingredient` DB I/O.

이 모듈만 SQLAlchemy 쿼리를 직접 쓴다 - PR #33의 `mfds_evidence_backfill.py`와 같은
전례(legacy `evidence` 임포트 당시 `mfds_importer.py`가 이미 이 패턴)를 따른다. Evidence
저장소에 아직 전용 `backend/repositories/`가 없고(현재 있는 건 읽기 전용 검색 repo뿐),
이 백필은 backend 업무 로직이 아니라 data 파트가 소유하는 1회성 변환 파이프라인이라
새 backend 파일을 만들지 않는다(CLAUDE.md 규칙 15 - 필요하면 계약만 쓰고 직접 만들지
않는다. 여기서는 기존 data/scripts 전례를 재사용하는 쪽을 택했다).

idempotency는 `evidence_chunk.chunk_id`의 기존 UNIQUE 제약(`uq_evidence_chunk_chunk_id`,
`models/evidence_chunk.py`)을 그대로 쓴다 - 새 컬럼/제약을 추가하지 않는다. 이미 존재하는
chunk_id는 건너뛰므로 재실행해도 중복 삽입되지 않고, 중단된 지점부터 자연히 이어진다.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.evidence_chunk import EvidenceChunk, evidence_chunk_ingredient
from models.evidence_document import EvidenceDocument, EvidenceDocumentSourceType

from data.scripts.mfds_evidence_backfill_schemas import EvidenceChunkStagingRecord


class MfdsEvidenceChunkLoader:
    """`evidence_document` 조회 + `evidence_chunk`/`evidence_chunk_ingredient` 삽입."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_document_ids_by_source_id(self) -> dict[str, UUID]:
        """PR #33이 만든 jurisdiction별 `EvidenceDocument`의 `source_id -> id` 매핑.

        문서가 아직 없으면(백필 미실행) 빈 dict를 돌려주고, 그 경우 호출한 쪽이 명확한
        에러로 중단해야 한다(규칙 7) - 문서 없이 `evidence_chunk.document_id`를 채울 수
        없기 때문이다.
        """
        result = await self._session.execute(
            select(EvidenceDocument.source_id, EvidenceDocument.id).where(
                EvidenceDocument.source_type == EvidenceDocumentSourceType.MFDS
            )
        )
        return {source_id: document_id for source_id, document_id in result.all()}

    async def load_existing_chunk_ids(self, chunk_ids: list[str]) -> set[str]:
        """이미 적재된 chunk_id 집합. 재실행 시 이 목록에 있는 chunk는 건너뛴다."""
        if not chunk_ids:
            return set()
        result = await self._session.execute(
            select(EvidenceChunk.chunk_id).where(EvidenceChunk.chunk_id.in_(chunk_ids))
        )
        return set(result.scalars().all())

    async def insert_chunk(
        self,
        record: EvidenceChunkStagingRecord,
        *,
        document_id: UUID,
        embedding: list[float],
        embedding_model: str,
    ) -> None:
        """chunk 한 건 + ingredient 링크 한 건을 세션에 추가한다. commit은 호출자 책임."""
        chunk = EvidenceChunk(
            document_id=document_id,
            chunk_id=record.chunk_id,
            source_type=record.source_type,
            source_title=record.source_title,
            page=None,
            section=None,
            chunk_index=record.chunk_index,
            content=record.content,
            content_hash=record.content_hash,
            parser_version=record.parser_version,
            embedding=embedding,
            embedding_model=embedding_model,
            url=record.url,
            doi=None,
            pmid=None,
            jurisdiction=record.jurisdiction,
            evidence_level=record.evidence_level,
        )
        self._session.add(chunk)
        await self._session.flush()  # chunk.id를 확보해야 링크 행을 만들 수 있다.
        await self._session.execute(
            evidence_chunk_ingredient.insert().values(
                evidence_chunk_id=chunk.id, ingredient_id=record.ingredient_id
            )
        )

    async def commit(self) -> None:
        """지금까지 삽입한 chunk 를 확정한다. 배치마다 호출해야 중단돼도 그 배치까지는 남고,
        재실행 시 기존 chunk_id 건너뛰기로 이어서 진행할 수 있다."""
        await self._session.commit()
