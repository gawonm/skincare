from uuid import uuid4

from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.schemas import RagDocument, RagDocumentField, RagDocumentMetadata
from models.rag_chunk import RagChunkField, RagConfidenceTier, RagSourceTable


def _metadata() -> RagDocumentMetadata:
    return RagDocumentMetadata(
        confidence_tier=RagConfidenceTier.STRUCTURED_KNOWLEDGE, source_title="테스트 출처"
    )


def test_chunk_creates_one_chunk_per_field() -> None:
    document = RagDocument(
        source_table=RagSourceTable.INGREDIENT_KNOWLEDGE_FACT,
        ingredient_id=uuid4(),
        ingredient_knowledge_fact_id=uuid4(),
        fields=(
            RagDocumentField(chunk_field=RagChunkField.KNOWLEDGE_EFFICACY, content="효능 설명"),
            RagDocumentField(chunk_field=RagChunkField.KNOWLEDGE_PRECAUTIONS, content="주의 설명"),
        ),
        metadata=_metadata(),
    )

    drafts = FieldChunker().chunk(document)

    assert len(drafts) == 2
    assert {draft.chunk_field for draft in drafts} == {
        RagChunkField.KNOWLEDGE_EFFICACY,
        RagChunkField.KNOWLEDGE_PRECAUTIONS,
    }
    assert all(
        draft.ingredient_knowledge_fact_id == document.ingredient_knowledge_fact_id
        for draft in drafts
    )


def test_chunk_empty_fields_produces_no_chunks() -> None:
    document = RagDocument(
        source_table=RagSourceTable.INGREDIENT_KNOWLEDGE_FACT,
        ingredient_knowledge_fact_id=uuid4(),
        fields=(),
        metadata=_metadata(),
    )

    assert FieldChunker().chunk(document) == []
