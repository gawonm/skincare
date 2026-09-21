"""선별된 `PubmedAssessment` 를 `EvidenceBundle` 로 바꾸는 순수 변환.

v1 은 1 PMID = document 1건, abstract 전체 = chunk 1건(`section="abstract"`, `chunk_index=0`)이다.
문장 분할·요약·재작성은 하지 않는다 - `content` 는 abstract 원문 그대로다.
"""

import hashlib
from datetime import datetime
from uuid import UUID

from data.scripts.evidence_collector_schemas import (
    EvidenceBundle,
    EvidenceChunkDraft,
    EvidenceDocumentDraft,
    PubmedAssessment,
)
from models.evidence_document import EvidenceDocumentSourceType, EvidenceLevel

PUBMED_PARSER_VERSION = "pubmed-abstract-v1"
_PUBMED_LANGUAGE = "en"
_ABSTRACT_SECTION = "abstract"
_ABSTRACT_CHUNK_INDEX = 0
_SOURCE_ID_PREFIX = "PMID"


class PubmedEvidenceMapper:
    def build_source_id(self, pmid: str) -> str:
        return f"{_SOURCE_ID_PREFIX}:{pmid}"

    def to_bundle(
        self,
        assessment: PubmedAssessment,
        *,
        ingredient_ids: list[UUID],
        raw_ingredient_names: list[str],
        retrieved_at: datetime,
    ) -> EvidenceBundle:
        record = assessment.record
        if not record.abstract:
            raise ValueError(
                f"abstract 가 없는 record 는 chunk 를 만들 수 없습니다: PMID {record.pmid}"
            )

        source_id = self.build_source_id(record.pmid)
        document = EvidenceDocumentDraft(
            source_type=EvidenceDocumentSourceType.PUBMED_ABSTRACT,
            source_id=source_id,
            source_title=record.title,
            publisher=record.journal,
            document_date=record.publication_date,
            url=record.url,
            doi=record.doi,
            pmid=record.pmid,
            language=_PUBMED_LANGUAGE,
            evidence_level=EvidenceLevel.PEER_REVIEWED_STUDY,
            raw_ingredient_names=raw_ingredient_names,
            document_status=None,
            study_type=assessment.study_type,
            formulation_type=assessment.formulation_type,
            claim_topics=assessment.claim_topics,
            retrieved_at=retrieved_at,
            ingredient_ids=ingredient_ids,
        )
        chunk = EvidenceChunkDraft(
            document_source_id=source_id,
            # PubMed 는 page 가 없어 자연키에서 page 자리를 뺀다(`PMID:16766489:abstract:0`)
            chunk_id=f"{source_id}:{_ABSTRACT_SECTION}:{_ABSTRACT_CHUNK_INDEX}",
            source_type=EvidenceDocumentSourceType.PUBMED_ABSTRACT,
            source_title=record.title,
            page=None,
            section=_ABSTRACT_SECTION,
            chunk_index=_ABSTRACT_CHUNK_INDEX,
            content=record.abstract,
            content_hash=hashlib.sha256(record.abstract.encode("utf-8")).hexdigest(),
            parser_version=PUBMED_PARSER_VERSION,
            url=record.url,
            doi=record.doi,
            pmid=record.pmid,
            evidence_level=EvidenceLevel.PEER_REVIEWED_STUDY,
            ingredient_ids=ingredient_ids,
        )
        return EvidenceBundle(document=document, chunks=[chunk])
