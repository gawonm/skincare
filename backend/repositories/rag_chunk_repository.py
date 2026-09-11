"""`rag_chunk` 저장·검색. pgvector 코사인 검색과 ParadeDB BM25 검색을 여기서 실행한다.

검색 알고리즘(코사인 거리, BM25 랭킹)이 SQL 쿼리 그 자체라 STRUCTURE.md 규칙("SQLAlchemy
쿼리는 backend/repositories/에만")을 따라 이 클래스가 소유한다. 검색 결과는
`RagChunkSearchHit`으로 반환하고 Backend service가 현재 Agent `RetrievedChunk`로 변환한다.
Agent는 세션이나 ORM을 직접 받지 않는다.

`RagChunkInsert`를 이 파일에 따로 두는 이유: `backend/repositories/`는 `models`만 import
한다는 규칙(import 방향)이 있어 `agent.rag.schemas.EmbeddedChunk`를 직접 받을 수 없다.
호출하는 쪽(`backend/services/`)이 `EmbeddedChunk`를 이 DTO로 변환해 넘긴다.
"""

import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.rag_chunk import RagChunk, RagChunkField, RagConfidenceTier, RagSourceTable

# ParadeDB `@@@`는 자체 쿼리 미니언어(field:term, AND/OR, 괄호 그룹핑)를 파싱한다. 자연어
# 질문을 그대로 넘기면 괄호·물음표 같은 문장부호가 그 문법과 충돌해서 파싱 에러가 난다
# (2026-09-10 실제로 재현됨: "...(파라벤류)...?" 질의가 InternalServerError로 실패).
# 그 문법에서 의미를 갖는 문자를 전부 지우고 단어 토큰만 남겨 안전하게 만든다.
_BM25_UNSAFE_CHARACTERS_PATTERN = re.compile(r"[^\w%]+", re.UNICODE)


class RagChunkInsert(BaseModel):
    """`RagChunkRepository.save_many`/`sync_documents`의 입력 한 건."""

    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID | None
    source_table: RagSourceTable
    evidence_id: UUID | None
    ingredient_knowledge_fact_id: UUID | None
    nia_record_id: str | None
    chunk_field: RagChunkField
    chunk_index: int
    content: str
    embedding: list[float]
    embedding_model: str
    confidence_tier: RagConfidenceTier
    cites_cir: bool
    source_title: str
    source_url: str | None
    citation_refs: list[str]

    def document_ref(self) -> str:
        """`ux_rag_chunk_natural_key`가 쓰는 문서 참조 문자열. 정확히 하나만 채워져 있다."""
        ref = self.evidence_id or self.ingredient_knowledge_fact_id or self.nia_record_id
        if ref is None:
            raise ValueError(
                "RagChunkInsert는 evidence_id/ingredient_knowledge_fact_id/nia_record_id 중 하나가 있어야 한다"
            )
        return str(ref)


class RagSyncResult(BaseModel):
    """`sync_documents` 실행 결과. 무엇이 실제로 바뀌었는지 검증할 때 쓴다."""

    model_config = ConfigDict(frozen=True)

    inserted: int
    updated: int
    unchanged: int
    deleted: int


class RagVectorSearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_vector: list[float] = Field(min_length=1)
    limit: int = Field(ge=1)
    target_ids: list[UUID] = Field(default_factory=list)
    embedding_model: str = Field(min_length=1)


class RagBm25SearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_text: str = Field(min_length=1)
    limit: int = Field(ge=1)
    target_ids: list[UUID] = Field(default_factory=list)
    embedding_model: str = Field(min_length=1)


class RagChunkSearchHit(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    chunk: RagChunk
    score: float


class RagChunkRepository:
    """`RagChunk` 조회·저장 전용. commit은 하지 않는다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_many(self, inserts: list[RagChunkInsert]) -> None:
        """중복 확인 없는 단순 삽입. 빈 테이블에 처음 채울 때만 쓴다 - 재적재에는 `sync_documents`를 쓴다."""
        self._session.add_all(self._to_rows(inserts))

    async def sync_documents(
        self, source_table: RagSourceTable, fetched_refs: list[str], inserts: list[RagChunkInsert]
    ) -> RagSyncResult:
        """`fetched_refs`에 있는 문서만 교체(replace)한다. 목록에 없는 문서는 절대 건드리지 않는다.

        `fetched_refs`는 이번 실행에서 원본 조회가 실제로 끝까지 성공한 문서만 담아야 한다.
        조회가 실패/부분 응답이었던 문서는 이 목록에서 빼서 넘기면, 그 문서의 기존 청크는
        그대로 남는다 - "새 청크가 0개"와 "이번에 못 가져왔다"를 호출부가 구분해서 알려주는
        방식이다(리포지토리 혼자서는 이 둘을 구분할 수 없다).
        """
        if not fetched_refs:
            return RagSyncResult(inserted=0, updated=0, unchanged=0, deleted=0)

        existing = await self._existing_by_ref(source_table, fetched_refs)
        new_by_key = {
            (insert.document_ref(), insert.chunk_field, insert.chunk_index): insert
            for insert in inserts
        }

        to_delete: list[UUID] = []
        to_update: list[tuple[RagChunk, RagChunkInsert]] = []
        seen_existing_keys: set[tuple[str, RagChunkField, int]] = set()
        unchanged = 0

        for ref, rows in existing.items():
            for row in rows:
                key = (ref, row.chunk_field, row.chunk_index)
                seen_existing_keys.add(key)
                new_insert = new_by_key.get(key)
                if new_insert is None:
                    # 원본에서 이 필드/청크가 사라졌다 - 삭제 대상.
                    to_delete.append(row.id)
                elif self._is_unchanged(row, new_insert):
                    unchanged += 1
                else:
                    to_update.append((row, new_insert))

        to_insert = [insert for key, insert in new_by_key.items() if key not in seen_existing_keys]

        if to_delete:
            await self._session.execute(delete(RagChunk).where(RagChunk.id.in_(to_delete)))
        for row, new_insert in to_update:
            self._apply(row, new_insert)
        if to_insert:
            self._session.add_all(self._to_rows(to_insert))

        return RagSyncResult(
            inserted=len(to_insert),
            updated=len(to_update),
            unchanged=unchanged,
            deleted=len(to_delete),
        )

    async def _existing_by_ref(
        self, source_table: RagSourceTable, fetched_refs: list[str]
    ) -> dict[str, list[RagChunk]]:
        ref_column = self._ref_column(source_table)
        statement = select(RagChunk).where(
            RagChunk.source_table == source_table, ref_column.in_(fetched_refs)
        )
        result = await self._session.execute(statement)
        grouped: dict[str, list[RagChunk]] = {}
        for row in result.scalars().all():
            ref = str(getattr(row, ref_column.key))
            grouped.setdefault(ref, []).append(row)
        return grouped

    def _ref_column(self, source_table: RagSourceTable):
        if source_table is RagSourceTable.EVIDENCE:
            return RagChunk.evidence_id
        if source_table is RagSourceTable.INGREDIENT_KNOWLEDGE_FACT:
            return RagChunk.ingredient_knowledge_fact_id
        return RagChunk.nia_record_id

    def _is_unchanged(self, row: RagChunk, insert: RagChunkInsert) -> bool:
        # embedding 값은 비교하지 않는다 - 실제로 확인해보니(2026-09-10) 같은 텍스트를 같은
        # 같은 모델도 장치·라이브러리 버전에 따라 벡터가 bit-identical하지 않을 수 있다.
        # content/embedding_model이 같으면 재사용 가능한 벡터로 보고,
        # 벡터 값 자체는 "바뀌었다"는 신호로 쓰지 않는다 - 안 그러면 재적재할 때마다 아무것도
        # 안 바뀌었는데도 매번 UPDATE가 발생해 updated_at이 계속 갱신된다.
        return (
            row.content == insert.content
            and row.embedding_model == insert.embedding_model
            and row.confidence_tier == insert.confidence_tier
            and row.cites_cir == insert.cites_cir
            and row.source_title == insert.source_title
            and row.source_url == insert.source_url
            and list(row.citation_refs) == list(insert.citation_refs)
        )

    def _apply(self, row: RagChunk, insert: RagChunkInsert) -> None:
        row.content = insert.content
        row.embedding = list(insert.embedding)
        row.embedding_model = insert.embedding_model
        row.confidence_tier = insert.confidence_tier
        row.cites_cir = insert.cites_cir
        row.source_title = insert.source_title
        row.source_url = insert.source_url
        row.citation_refs = list(insert.citation_refs)

    def _to_rows(self, inserts: list[RagChunkInsert]) -> list[RagChunk]:
        return [
            RagChunk(
                ingredient_id=insert.ingredient_id,
                source_table=insert.source_table,
                evidence_id=insert.evidence_id,
                ingredient_knowledge_fact_id=insert.ingredient_knowledge_fact_id,
                nia_record_id=insert.nia_record_id,
                chunk_field=insert.chunk_field,
                chunk_index=insert.chunk_index,
                content=insert.content,
                embedding=list(insert.embedding),
                embedding_model=insert.embedding_model,
                confidence_tier=insert.confidence_tier,
                cites_cir=insert.cites_cir,
                source_title=insert.source_title,
                source_url=insert.source_url,
                citation_refs=list(insert.citation_refs),
            )
            for insert in inserts
        ]

    async def search_by_vector(self, request: RagVectorSearchRequest) -> list[RagChunkSearchHit]:
        """반환값의 float는 코사인 유사도(1 - 거리, 클수록 유사)다.

        원문 관련성 판정(자유 텍스트 질문이 실제로 근거와 관련 있는지)에는 순위만으로는
        부족하고 원점수가 필요하다 - RRF 순위는 상대적 순서일 뿐 "이 결과가 질문과 실제로
        가까운가"는 말해주지 않는다(2026-09-10 지적).
        """
        distance = RagChunk.embedding.cosine_distance(request.query_vector)
        statement = select(RagChunk, (1 - distance).label("similarity"))
        statement = statement.where(
            RagChunk.embedding_model == request.embedding_model,
            RagChunk.source_table.in_(
                (RagSourceTable.EVIDENCE, RagSourceTable.INGREDIENT_KNOWLEDGE_FACT)
            ),
        )
        if request.target_ids:
            statement = statement.where(RagChunk.ingredient_id.in_(request.target_ids))
        statement = statement.order_by(distance).limit(request.limit)
        result = await self._session.execute(statement)
        return [RagChunkSearchHit(chunk=row.RagChunk, score=row.similarity) for row in result]

    async def search_by_bm25(self, request: RagBm25SearchRequest) -> list[RagChunkSearchHit]:
        """반환값의 float는 ParadeDB BM25 점수(클수록 관련성 높음)다."""
        # ParadeDB pg_search 연산자. `@@@`는 인덱싱된 컬럼에 대한 BM25 매치 조건이다.
        safe_query_text = self._sanitize_bm25_query(request.query_text)
        if not safe_query_text:
            return []
        score = func.paradedb.score(RagChunk.id)
        statement = select(RagChunk, score.label("score")).where(
            RagChunk.content.op("@@@")(safe_query_text),
            RagChunk.embedding_model == request.embedding_model,
            RagChunk.source_table.in_(
                (RagSourceTable.EVIDENCE, RagSourceTable.INGREDIENT_KNOWLEDGE_FACT)
            ),
        )
        if request.target_ids:
            statement = statement.where(RagChunk.ingredient_id.in_(request.target_ids))
        statement = statement.order_by(score.desc()).limit(request.limit)
        result = await self._session.execute(statement)
        return [RagChunkSearchHit(chunk=row.RagChunk, score=row.score) for row in result]

    def _sanitize_bm25_query(self, query_text: str) -> str:
        return _BM25_UNSAFE_CHARACTERS_PATTERN.sub(" ", query_text).strip()
