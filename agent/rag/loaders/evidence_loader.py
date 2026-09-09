"""`Evidence`(공식 규제 근거) 행을 `RagDocument`로 바꾼다.

DB 세션을 직접 열지 않는다 - 이미 조회된 `list[Evidence]`를 받는다(호출부가
`EvidenceRepository`로 조회한 뒤 넘긴다).
"""

from agent.rag.schemas import RagDocument, RagDocumentField, RagDocumentMetadata
from models.evidence import Evidence
from models.rag_chunk import RagChunkField, RagConfidenceTier, RagSourceTable


class EvidenceLoader:
    """`Evidence` 목록을 소스 무관 공통 문서 형태로 변환한다."""

    def load(self, rows: list[Evidence]) -> list[RagDocument]:
        return [self._to_document(row) for row in rows]

    def _to_document(self, row: Evidence) -> RagDocument:
        fields = [RagDocumentField(chunk_field=RagChunkField.EVIDENCE_CLAIM, content=row.claim)]
        if row.conditions:
            fields.append(
                RagDocumentField(
                    chunk_field=RagChunkField.EVIDENCE_CONDITIONS, content=row.conditions
                )
            )

        return RagDocument(
            source_table=RagSourceTable.EVIDENCE,
            ingredient_id=row.ingredient_id,
            evidence_id=row.id,
            fields=tuple(fields),
            metadata=RagDocumentMetadata(
                # Evidence는 CIR·MFDS 등 공식 출처만 담는다는 원칙이 이미 models/evidence.py에
                # 있으므로 항상 최상위 신뢰도로 취급한다.
                confidence_tier=RagConfidenceTier.OFFICIAL_REGULATORY,
                source_title=row.source_title,
                source_url=row.source_url,
                citation_refs=(),
                cites_cir=False,
            ),
        )
