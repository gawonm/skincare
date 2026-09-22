from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.rag.case_schemas import CaseDatasetSplit, CaseSearchRequest
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingVector,
    LocalEmbeddingModel,
    LookupStatus,
)
from backend.repositories.nia_case_document_repository import (
    NiaCaseDocumentRepository,
    NiaCaseSearchRow,
    NiaCaseVectorSearchRequest,
)
from backend.services import two_layer_rag_adapters
from backend.services.two_layer_rag_adapters import BackendNiaCaseRetriever
from models.nia_case_document import NiaCaseDatasetSplit


class NiaCaseSearchFixture:
    def request(
        self,
        *,
        embedding_model: str = LocalEmbeddingModel.BGE_M3.value,
        dimensions: int = BGE_M3_EMBEDDING_DIMENSIONS,
    ) -> CaseSearchRequest:
        return CaseSearchRequest(
            query="피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?",
            query_embedding=EmbeddingVector(values=[0.1] * dimensions),
            text_version="nia_case_text/v1",
            embedding_model=embedding_model,
            candidate_limit=20,
        )

    def row(self) -> NiaCaseSearchRow:
        return NiaCaseSearchRow(
            case_id="case-1",
            dataset_split=NiaCaseDatasetSplit.TRAINING,
            source_archive_name="training.zip",
            source_member_name="records.jsonl",
            source_line_number=12,
            page_content="[질문]\n피지가 많습니다.\n[답변]\n나이아신아마이드를 권합니다.",
            text_version="nia_case_text/v1",
            target_concern="피지",
            gender="여성",
            age=25,
            skin_type="지성",
            skin_concerns=["피지", "여드름"],
            vector_similarity=0.87,
        )

    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=MagicMock(spec=AsyncSession))
        context.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=context)
        return cast(async_sessionmaker[AsyncSession], factory)


class TestNiaCaseDocumentSearchRepository:
    @pytest.mark.asyncio
    async def test_버전과_모델을_고정하고_cosine_유사도로_검색한다(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        result = MagicMock()
        result.mappings.return_value.all.return_value = []
        session.execute.return_value = result
        repository = NiaCaseDocumentRepository(cast(AsyncSession, session))

        rows = await repository.search_by_vector(
            NiaCaseVectorSearchRequest(
                query_vector=[0.0] * BGE_M3_EMBEDDING_DIMENSIONS,
                text_version="nia_case_text/v1",
                embedding_model=LocalEmbeddingModel.BGE_M3.value,
                limit=20,
            )
        )

        statement = session.execute.await_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": False},
            )
        )
        assert rows == []
        assert "nia_case_document.text_version" in compiled
        assert "nia_case_document.embedding_model" in compiled
        assert "<=>" in compiled
        assert "ORDER BY" in compiled
        assert "LIMIT" in compiled


class TestBackendNiaCaseRetriever:
    @pytest.mark.asyncio
    async def test_DB_행을_Agent_Case_hit으로_변환한다(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fixture = NiaCaseSearchFixture()
        repository = MagicMock()
        repository.search_by_vector = AsyncMock(return_value=[fixture.row()])
        repository_factory = MagicMock(return_value=repository)
        monkeypatch.setattr(
            two_layer_rag_adapters,
            "NiaCaseDocumentRepository",
            repository_factory,
        )
        retriever = BackendNiaCaseRetriever(fixture.session_factory())

        result = await retriever.search(fixture.request())

        assert result.status is LookupStatus.SUCCESS
        assert len(result.hits) == 1
        assert result.hits[0].case_id == "case-1"
        assert result.hits[0].dataset_split is CaseDatasetSplit.TRAINING
        assert result.hits[0].metadata.skin_concerns == ["피지", "여드름"]
        assert result.hits[0].provenance.line_number == 12
        repository.search_by_vector.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_BGE_M3가_아닌_질의는_DB_조회_전에_거부한다(self) -> None:
        fixture = NiaCaseSearchFixture()
        retriever = BackendNiaCaseRetriever(fixture.session_factory())

        result = await retriever.search(fixture.request(embedding_model="other-model"))

        assert result.status is LookupStatus.UNSUPPORTED
        assert result.hits == []
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_1024차원이_아닌_질의는_DB_조회_전에_거부한다(self) -> None:
        fixture = NiaCaseSearchFixture()
        retriever = BackendNiaCaseRetriever(fixture.session_factory())

        result = await retriever.search(fixture.request(dimensions=3))

        assert result.status is LookupStatus.UNSUPPORTED
        assert result.hits == []
        assert result.error_message is not None
