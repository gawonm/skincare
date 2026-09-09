"""`RagDocument`를 `RagChunkDraft` 목록으로 자른다.

"의미단위 하나 = 청크 하나" 원칙만 쓴다 - 길이 기반 스플리터는 여기서 쓰지 않는다.
각 필드는 이미 로더 단계에서 하나의 사실/문단 단위로 분리돼 있으므로, 청킹은
`RagDocumentField`를 그대로 `RagChunkDraft`로 옮기는 일만 한다.
"""

from agent.rag.schemas import RagChunkDraft, RagDocument


class FieldChunker:
    """`RagDocument.fields`를 `RagChunkDraft` 목록으로 변환한다."""

    def chunk(self, document: RagDocument) -> list[RagChunkDraft]:
        return [
            RagChunkDraft(
                source_table=document.source_table,
                ingredient_id=document.ingredient_id,
                evidence_id=document.evidence_id,
                ingredient_knowledge_fact_id=document.ingredient_knowledge_fact_id,
                nia_record_id=document.nia_record_id,
                chunk_field=field.chunk_field,
                chunk_index=field.chunk_index,
                content=field.content,
                metadata=document.metadata,
            )
            for field in document.fields
        ]
