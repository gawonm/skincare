"""Backend ORM 근거를 Agent 소유 저장소 독립 문서로 변환한다."""

from agent.rag.loaders.data_records import (
    DataRecordMapper,
    DataSourceContext,
    EvidenceData,
    EvidenceDataRequest,
    KnowledgeFactData,
    KnowledgeFactRequest,
)
from agent.rag.schemas import (
    QuestionIntent,
    RagConfidenceTier,
    RagDocument,
    RagDocumentField,
    RegulateType,
    RegulatoryConfidence,
)
from models.evidence import Evidence
from models.ingredient_knowledge import IngredientKnowledgeFact
from models.rag_chunk import RagChunkField


class RagDocumentMapper:
    """DB 타입을 Agent로 넘기지 않고 명시적인 Pydantic DTO 경계를 만든다."""

    def __init__(self) -> None:
        self._records = DataRecordMapper()

    def evidence(self, rows: list[Evidence]) -> list[RagDocument]:
        return [self._evidence_document(row) for row in rows]

    def knowledge(self, rows: list[IngredientKnowledgeFact]) -> list[RagDocument]:
        return [document for row in rows if (document := self._knowledge_document(row))]

    def _evidence_document(self, row: Evidence) -> RagDocument:
        regulate_type = RegulateType(row.regulate_type.value) if row.regulate_type else None
        record = self._records.mfds(
            EvidenceDataRequest(
                data=EvidenceData(
                    id=row.id,
                    ingredient_id=row.ingredient_id,
                    claim=row.claim,
                    conditions=row.conditions,
                    jurisdiction=row.jurisdiction,
                    source_title=row.source_title,
                    source_url=row.source_url,
                    published_at=row.published_at,
                    collected_at=row.collected_at,
                    regulate_type=regulate_type,
                ),
                source=DataSourceContext(
                    source_id=f"evidence:{row.id}",
                    source_title=row.source_title,
                    locator=f"evidence:{row.id}",
                ),
            )
        )
        fields = [
            RagDocumentField(
                field_id=RagChunkField.EVIDENCE_CLAIM.value,
                content=row.claim,
                intents=[QuestionIntent.REGULATION, QuestionIntent.PRECAUTION],
            )
        ]
        if row.conditions:
            fields.append(
                RagDocumentField(
                    field_id=RagChunkField.EVIDENCE_CONDITIONS.value,
                    content=row.conditions,
                    intents=[QuestionIntent.CONCENTRATION, QuestionIntent.PRECAUTION],
                )
            )
        return RagDocument(
            evidence=record,
            fields=fields,
            confidence_tier=RagConfidenceTier.OFFICIAL_REGULATORY,
        )

    def _knowledge_document(self, row: IngredientKnowledgeFact) -> RagDocument | None:
        record = self._records.knowledge(
            KnowledgeFactRequest(
                data=KnowledgeFactData(
                    id=row.id,
                    ingredient_id=row.ingredient_id,
                    source_row_no=row.source_row_no,
                    inci_name=row.inci_name,
                    efficacy=row.efficacy,
                    recommended_skin_types=row.recommended_skin_types,
                    precautions=row.precautions,
                    recommended_concentration=row.recommended_concentration,
                    compounding_regulation_text=row.compounding_regulation_text,
                    source_reference=row.source_reference,
                    regulatory_confidence=RegulatoryConfidence(row.regulatory_confidence.value),
                ),
                source=DataSourceContext(
                    source_id=f"ingredient_knowledge_fact:{row.id}",
                    source_title=f"{row.inci_name} 성분 지식 (Knowledgedata)",
                    locator=f"Knowledgedata row {row.source_row_no}",
                ),
            )
        )
        fields = self._knowledge_fields(row)
        if not fields:
            return None
        return RagDocument(
            evidence=record,
            fields=fields,
            confidence_tier=RagConfidenceTier.STRUCTURED_KNOWLEDGE,
        )

    def _knowledge_fields(self, row: IngredientKnowledgeFact) -> list[RagDocumentField]:
        candidates = (
            (RagChunkField.KNOWLEDGE_EFFICACY, row.efficacy, [QuestionIntent.EFFICACY]),
            (
                RagChunkField.KNOWLEDGE_RECOMMENDED_SKIN_TYPES,
                row.recommended_skin_types,
                [QuestionIntent.SKIN_TYPE],
            ),
            (
                RagChunkField.KNOWLEDGE_PRECAUTIONS,
                row.precautions,
                [QuestionIntent.PRECAUTION],
            ),
            (
                RagChunkField.KNOWLEDGE_RECOMMENDED_CONCENTRATION,
                row.recommended_concentration,
                [QuestionIntent.CONCENTRATION],
            ),
        )
        return [
            RagDocumentField(field_id=field.value, content=content, intents=intents)
            for field, content, intents in candidates
            if content
        ]
