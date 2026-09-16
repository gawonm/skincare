"""저장된 Evidence 메타데이터를 응답 Citation으로 변환한다."""

from agent.rag.schemas import EvidenceRecord
from agent.schemas import Citation


class EvidenceCitationMapper:
    """LLM 문장이 아니라 검색 결과의 메타데이터만 인용 정보로 사용한다."""

    def map(self, record: EvidenceRecord) -> Citation:
        return Citation(
            source_type=record.source_type,
            text_kind=record.text_kind,
            scope=record.scope,
            jurisdiction=record.jurisdiction,
            evidence_id=record.evidence_id,
            source_id=record.source_id,
            locator=record.locator,
            source_title=record.source_title,
            document_version=record.document_version,
            url=record.url,
            is_demo=record.is_demo,
        )
