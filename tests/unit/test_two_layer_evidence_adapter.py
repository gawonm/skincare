"""2-Layer Evidence 문서 등급을 Agent 신뢰등급으로 보존하는지 검사한다."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.rag.schemas import EvidenceReviewStatus, RagConfidenceTier
from backend.repositories.evidence_search_repository import EvidenceSearchRow
from backend.services.two_layer_rag_adapters import TwoLayerEvidenceSearchBackend


class TestTwoLayerEvidenceAdapter:
    def _backend(self) -> TwoLayerEvidenceSearchBackend:
        return TwoLayerEvidenceSearchBackend(
            cast(async_sessionmaker[AsyncSession], object())
        )

    def _row(self, evidence_level: str) -> EvidenceSearchRow:
        return EvidenceSearchRow(
            evidence_id=UUID("00000000-0000-0000-0000-000000000001"),
            source_id="source-1",
            document_source_type="cir",
            source_title="테스트 출처",
            evidence_level=evidence_level,
            document_status=None,
            claim_topics=["regulation"],
            retrieved_at=datetime(2026, 9, 22, tzinfo=UTC),
            chunk_id="chunk-1",
            chunk_source_type="section",
            chunk_index=0,
            content="테스트 근거",
            target_ids=[UUID("00000000-0000-0000-0000-000000000002")],
            score=0.9,
        )

    @pytest.mark.parametrize(
        ("evidence_level", "expected"),
        [
            ("official_regulatory", RagConfidenceTier.OFFICIAL_REGULATORY),
            ("expert_reviewed", RagConfidenceTier.STRUCTURED_KNOWLEDGE),
            ("peer_reviewed_study", RagConfidenceTier.STRUCTURED_KNOWLEDGE),
        ],
    )
    def test_official_document_levels_remain_answer_eligible(
        self,
        evidence_level: str,
        expected: RagConfidenceTier,
    ) -> None:
        retrieved = self._backend()._to_retrieved(self._row(evidence_level), vector=True)

        assert retrieved.chunk.confidence_tier is expected
        assert retrieved.chunk.evidence.review_status is EvidenceReviewStatus.UNREVIEWED
