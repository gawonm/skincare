import pytest
from pydantic import ValidationError

from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.schemas import (
    EvidenceRecord,
    EvidenceReviewStatus,
    QuestionIntent,
    RagConfidenceTier,
    RagDocument,
    RagDocumentField,
)


class TestFieldChunker:
    def _evidence(self) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id="evidence-1",
            source_id="source-1",
            source_title="테스트 출처",
            text="효능과 주의 설명",
            locator="test:1",
            target_ids=["ingredient-1"],
            review_status=EvidenceReviewStatus.VERIFIED,
            is_demo=False,
        )

    def test_chunk_creates_one_chunk_per_field(self) -> None:
        document = RagDocument(
            evidence=self._evidence(),
            fields=[
                RagDocumentField(
                    field_id="knowledge_efficacy",
                    content="효능 설명",
                    intents=[QuestionIntent.EFFICACY],
                ),
                RagDocumentField(
                    field_id="knowledge_precautions",
                    content="주의 설명",
                    intents=[QuestionIntent.PRECAUTION],
                ),
            ],
            confidence_tier=RagConfidenceTier.STRUCTURED_KNOWLEDGE,
        )

        drafts = FieldChunker().chunk(document)

        assert len(drafts) == 2
        assert {draft.field_id for draft in drafts} == {
            "knowledge_efficacy",
            "knowledge_precautions",
        }
        assert all(draft.evidence == document.evidence for draft in drafts)

    def test_document_requires_at_least_one_field(self) -> None:
        with pytest.raises(ValidationError):
            RagDocument(evidence=self._evidence(), fields=[])
