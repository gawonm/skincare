"""compact Evidence collector(PubMed/CIR)가 주고받는 Enum 과 Pydantic 모델.

collector 는 DB 에 쓰지 않고 `EvidenceDocumentDraft`/`EvidenceChunkDraft` 까지만 만든다.
`evidence_chunk.embedding` 이 NOT NULL 이라 chunk 를 바로 INSERT 할 수 없고, 임베딩·적재는
기존 MFDS 파이프라인처럼 이후 단계가 draft 파일을 읽어 수행한다.
"""

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models.evidence_document import (
    EvidenceClaimTopic,
    EvidenceDocumentSourceType,
    EvidenceDocumentStatus,
    EvidenceFormulationType,
    EvidenceLevel,
    EvidenceStudyType,
)


class EvidenceCollectionSource(StrEnum):
    PUBMED = "pubmed"
    CIR = "cir"


class CollectionIngredient(BaseModel):
    """collector 입력. Tier A 는 병렬 작업에서 정해지므로 호출자가 이 목록을 넘긴다."""

    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    standard_name_en: str
    standard_name_ko: str | None = None
    aliases: list[str] = Field(default_factory=list)


class PubmedRecord(BaseModel):
    """EFetch 응답 한 편. authors 는 Evidence 스키마에 저장 컬럼이 없어 raw metadata 로만 둔다."""

    model_config = ConfigDict(frozen=True)

    pmid: str
    doi: str | None
    title: str
    abstract: str | None
    journal: str | None
    publication_date: date | None
    publication_types: list[str]
    mesh_terms: list[str]
    authors: list[str]

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


class PubmedSelectionDisposition(StrEnum):
    SELECTED = "selected"
    # 자동으로 evidence 확정하기엔 불확실해 사람이 검토하도록 남기는 후보
    CANDIDATE = "candidate"
    REJECTED = "rejected"


class PubmedSelectionReason(StrEnum):
    NO_ABSTRACT = "no_abstract"
    EXCLUDED_PUBLICATION_TYPE = "excluded_publication_type"
    NOT_RELEVANT_TO_INGREDIENT = "not_relevant_to_ingredient"
    INGREDIENT_NOT_IN_TITLE = "ingredient_not_in_title"
    STUDY_TYPE_NOT_SELECTABLE = "study_type_not_selectable"
    OVER_BUDGET = "over_budget"


class PubmedAssessment(BaseModel):
    """한 성분에 대한 PubMed record 한 편의 결정적(deterministic) 평가 결과."""

    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    record: PubmedRecord
    study_type: EvidenceStudyType
    formulation_type: EvidenceFormulationType
    claim_topics: list[EvidenceClaimTopic]
    score: int
    disposition: PubmedSelectionDisposition
    reason: PubmedSelectionReason | None = None


class EvidenceDocumentDraft(BaseModel):
    """`evidence_document` INSERT 직전 값(성분 연결은 ingredient_ids 로 따로 든다)."""

    model_config = ConfigDict(frozen=True)

    source_type: EvidenceDocumentSourceType
    source_id: str
    source_title: str
    publisher: str | None
    document_date: date | None
    url: str | None
    doi: str | None
    pmid: str | None
    language: str
    evidence_level: EvidenceLevel
    raw_ingredient_names: list[str]
    document_status: EvidenceDocumentStatus | None
    study_type: EvidenceStudyType | None
    formulation_type: EvidenceFormulationType | None
    claim_topics: list[EvidenceClaimTopic]
    retrieved_at: datetime
    ingredient_ids: list[UUID]


class EvidenceChunkDraft(BaseModel):
    """`evidence_chunk` INSERT 직전 값. `embedding`/`embedding_model` 만 없다."""

    model_config = ConfigDict(frozen=True)

    document_source_id: str
    chunk_id: str
    source_type: EvidenceDocumentSourceType
    source_title: str
    page: int | None
    section: str | None
    chunk_index: int
    content: str
    content_hash: str
    parser_version: str
    url: str | None
    doi: str | None
    pmid: str | None
    evidence_level: EvidenceLevel
    ingredient_ids: list[UUID]


class EvidenceBundle(BaseModel):
    """document 1건과 그에 속한 chunk 들. draft JSONL 의 한 줄이다."""

    model_config = ConfigDict(frozen=True)

    document: EvidenceDocumentDraft
    chunks: list[EvidenceChunkDraft]


class CirReportCandidate(BaseModel):
    """CIR ingredient/status 페이지에서 발견한 report(=attachment) 한 건.

    group review 는 하나의 report 가 여러 성분을 다루므로 ingredient_ids 가 여러 개일 수 있다.
    """

    model_config = ConfigDict(frozen=True)

    attachment_id: str
    title: str
    status_label: str
    # status 페이지 라벨은 원본과 amended 모두 "Published Report" 라서 라벨만으로 구분할 수 없다
    is_amended: bool = False
    publisher: str | None = None
    document_date: date | None = None
    doi: str | None = None
    status_page_url: str | None = None
    ingredient_ids: list[UUID]
    raw_ingredient_names: list[str] = Field(default_factory=list)
    pdf_path: Path | None = None


class CirChunkingWarning(StrEnum):
    NO_SECTIONS_DETECTED = "no_sections_detected"
    NO_TARGET_SECTIONS = "no_target_sections"


class CirChunkingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    detected_sections: list[str]
    chunks: list[EvidenceChunkDraft]
    warnings: list[CirChunkingWarning]


class PubmedCollectionResult(BaseModel):
    """성분 하나에 대한 PubMed 수집 결과. selected/candidates 는 `assessments` 에서 파생한다."""

    model_config = ConfigDict(frozen=True)

    ingredient: CollectionIngredient
    assessments: list[PubmedAssessment]
    queries_run: int

    @property
    def selected(self) -> list[PubmedAssessment]:
        return [a for a in self.assessments if a.disposition is PubmedSelectionDisposition.SELECTED]

    @property
    def candidates(self) -> list[PubmedAssessment]:
        return [
            a for a in self.assessments if a.disposition is PubmedSelectionDisposition.CANDIDATE
        ]
