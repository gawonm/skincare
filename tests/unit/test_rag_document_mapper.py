from datetime import UTC, datetime
from uuid import uuid4

from agent.rag.schemas import EvidenceSourceType, QuestionIntent
from backend.services.rag_document_mapper import RagDocumentMapper
from models.evidence import (
    Evidence,
    EvidenceRegulateType,
    EvidenceTopic,
)
from models.evidence import (
    EvidenceSourceType as DatabaseEvidenceSourceType,
)
from models.ingredient_knowledge import IngredientKnowledgeFact, RegulatoryConfidence


class TestRagDocumentMapper:
    def test_evidence_keeps_conditions_and_search_intents(self) -> None:
        row = Evidence(
            id=uuid4(),
            ingredient_id=uuid4(),
            topic=EvidenceTopic.COSMETIC_USE_RESTRICTION,
            claim="한국 배합 규제",
            conditions="1.0% 이하",
            jurisdiction="한국",
            regulate_type=EvidenceRegulateType.LIMITED,
            source_type=DatabaseEvidenceSourceType.MFDS_RESTRICTED_INGREDIENT,
            source_title="식품의약품안전처",
            source_url="https://example.com/mfds",
            collected_at=datetime.now(UTC),
        )

        document = RagDocumentMapper().evidence([row])[0]

        assert document.evidence.source_type is EvidenceSourceType.MFDS
        assert document.evidence.raw_conditions == "1.0% 이하"
        assert {field.field_id for field in document.fields} == {
            "evidence_claim",
            "evidence_conditions",
        }
        assert QuestionIntent.REGULATION in document.fields[0].intents

    def test_unverified_knowledge_regulation_is_not_sent_to_generator(self) -> None:
        row = IngredientKnowledgeFact(
            id=uuid4(),
            ingredient_id=uuid4(),
            source_row_no=1,
            inci_name="Retinol",
            efficacy="피부 컨디셔닝",
            compounding_regulation_text="검증되지 않은 배합 규제",
            regulatory_confidence=RegulatoryConfidence.UNVERIFIED,
        )

        document = RagDocumentMapper().knowledge([row])[0]

        assert "피부 컨디셔닝" in document.evidence.text
        assert "검증되지 않은 배합 규제" not in document.evidence.text
