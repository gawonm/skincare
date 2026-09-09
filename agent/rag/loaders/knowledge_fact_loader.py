"""`IngredientKnowledgeFact`(Knowledgedata) 행을 `RagDocument`로 바꾼다.

DB 세션을 직접 열지 않는다 - 이미 조회된 `list[IngredientKnowledgeFact]`를 받는다.

`compounding_regulation_text`는 청킹 대상에서 제외한다. 이 컬럼은 models/ingredient_knowledge.py
자체 문서에 "MFDS와 교차검증되기 전까지 국내 배합 규제에 관한 확정적 답변의 근거로 쓰지
않는다"고 명시돼 있다 - RAG가 이 텍스트를 근거로 답하면 그 원칙을 어기게 된다.
"""

from agent.rag.schemas import RagDocument, RagDocumentField, RagDocumentMetadata
from models.ingredient_knowledge import IngredientKnowledgeFact
from models.rag_chunk import RagChunkField, RagConfidenceTier, RagSourceTable

# 이 두 출처 텍스트에 이 키워드가 있으면 CIR(Cosmetic Ingredient Review) 안전성 평가를
# 인용하고 있다고 본다. CIR 안전성 근거 1단계(별도 스크래핑 없이 기존 텍스트에서 식별).
_CIR_CITATION_KEYWORD = "CIR"


class IngredientKnowledgeFactLoader:
    """`IngredientKnowledgeFact` 목록을 소스 무관 공통 문서 형태로 변환한다."""

    def load(self, rows: list[IngredientKnowledgeFact]) -> list[RagDocument]:
        return [self._to_document(row) for row in rows]

    def _to_document(self, row: IngredientKnowledgeFact) -> RagDocument:
        fields: list[RagDocumentField] = []
        if row.efficacy:
            fields.append(
                RagDocumentField(chunk_field=RagChunkField.KNOWLEDGE_EFFICACY, content=row.efficacy)
            )
        if row.recommended_skin_types:
            fields.append(
                RagDocumentField(
                    chunk_field=RagChunkField.KNOWLEDGE_RECOMMENDED_SKIN_TYPES,
                    content=row.recommended_skin_types,
                )
            )
        if row.precautions:
            fields.append(
                RagDocumentField(
                    chunk_field=RagChunkField.KNOWLEDGE_PRECAUTIONS, content=row.precautions
                )
            )
        if row.recommended_concentration:
            fields.append(
                RagDocumentField(
                    chunk_field=RagChunkField.KNOWLEDGE_RECOMMENDED_CONCENTRATION,
                    content=row.recommended_concentration,
                )
            )

        return RagDocument(
            source_table=RagSourceTable.INGREDIENT_KNOWLEDGE_FACT,
            ingredient_id=row.ingredient_id,
            ingredient_knowledge_fact_id=row.id,
            fields=tuple(fields),
            metadata=RagDocumentMetadata(
                confidence_tier=RagConfidenceTier.STRUCTURED_KNOWLEDGE,
                source_title=f"{row.inci_name} 성분 지식 (Knowledgedata)",
                source_url=None,
                citation_refs=(),
                cites_cir=self._cites_cir(row),
            ),
        )

    def _cites_cir(self, row: IngredientKnowledgeFact) -> bool:
        haystacks = (row.source_reference, row.copyright_resolution)
        return any(
            haystack is not None and _CIR_CITATION_KEYWORD in haystack for haystack in haystacks
        )
