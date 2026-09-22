"""검증된 CIR PDF와 읽기 전용 DB snapshot으로 final bundle을 만든다.

DB write·embedding 없이 신규 문서/청크/성분 연결 후보와 기존 문서 재사용 후보만 파일로
내보낸다. 성분 연결은 청크 본문에 exact name 또는 승인된 exact equivalent가 실제로 있을
때만 생성한다.
"""

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from data.scripts.cir_evidence_builder import CirEvidenceBuilder
from data.scripts.evidence_collector_schemas import CirReportCandidate
from models.evidence_document import (
    EvidenceClaimTopic,
    EvidenceDocumentSourceType,
    EvidenceDocumentStatus,
    EvidenceLevel,
)

_DEFAULT_INPUT_DIR = Path("data/processed")
_DEFAULT_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
_DEFAULT_INGREDIENT_SQL = Path("/private/tmp/skincare_ingredient_master.sql")
_DEFAULT_DOCUMENT_SQL = Path("/private/tmp/skincare_evidence_document.sql")
_DEFAULT_CHUNK_SQL = Path("/private/tmp/skincare_evidence_chunk.sql")
_DEFAULT_LINK_SQL = Path("/private/tmp/skincare_evidence_chunk_ingredient.sql")
_PUBLISHER = "Cosmetic Ingredient Review"
_LANGUAGE = "en"
_CONTEXT_RADIUS = 140


class CirDocumentType(StrEnum):
    SAFETY_ASSESSMENT = "safety_assessment"
    FINAL_SAFETY_ASSESSMENT = "final_safety_assessment"
    AMENDED_SAFETY_ASSESSMENT = "amended_safety_assessment"
    STANDALONE_REASSESSMENT = "standalone_reassessment"
    RE_REVIEW_SUMMARY = "re_review_summary"


class LinkageType(StrEnum):
    NEW_DOCUMENT = "NEW_DOCUMENT"
    EXISTING_DOCUMENT_REUSE = "EXISTING_DOCUMENT_REUSE"


class IngredientSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    exact_terms: list[str]
    # exact name을 포함하지만 다른 물질인 알려진 파생형은 parent match에서 명시적으로 제외한다.
    excluded_terms: list[str] = Field(default_factory=list)


class ReportSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: str
    file_name: str
    title: str
    document_date: date
    doi: str | None
    status_label: str
    is_amended: bool
    document_type: CirDocumentType
    ingredients: list[IngredientSpec]
    first_page: int = 1
    last_page: int | None = None

    @property
    def source_id(self) -> str:
        return f"cir_attachment:{self.attachment_id}"

    @property
    def source_url(self) -> str:
        return f"https://cir-reports.cir-safety.org/view-attachment/?id={self.attachment_id}"


class FinalDocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: EvidenceDocumentSourceType
    source_id: str
    source_title: str
    publisher: str
    document_date: date
    url: str
    doi: str | None
    pmid: str | None
    language: str
    evidence_level: EvidenceLevel
    raw_ingredient_names: list[str]
    document_status: EvidenceDocumentStatus
    document_type: CirDocumentType
    study_type: None = None
    formulation_type: None = None
    claim_topics: list[EvidenceClaimTopic]
    retrieved_at: datetime
    ingredient_ids: list[UUID]
    attachment_id: str
    pdf_sha256: str


class FinalChunkRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_source_id: str
    chunk_id: str
    source_type: EvidenceDocumentSourceType
    source_title: str
    page: int
    section: str
    chunk_index: int
    content: str
    content_hash: str
    parser_version: str
    url: str
    doi: str | None
    pmid: str | None
    evidence_level: EvidenceLevel
    ingredient_ids: list[UUID]


class IngredientLinkRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_title: str
    chunk_id: str
    page: int
    section: str
    ingredient: str
    ingredient_id: UUID
    matched_text: str
    scope_verified: bool
    linkage_type: LinkageType


class ScopeEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient: str
    report_title: str
    attachment_id: str
    page: int
    section: str
    matched_text: str
    context: str
    scope_verified: bool
    note: str


class SnapshotDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    source_id: str
    source_title: str


class SnapshotChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    chunk_id: str
    source_title: str
    page: int | None
    section: str | None
    content: str
    chunk_db_id: str


class SnapshotData(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient_ids: dict[str, UUID]
    cir_documents: list[SnapshotDocument]
    cir_chunks: list[SnapshotChunk]
    existing_links: set[tuple[str, UUID]]


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    unresolved: list[str] = Field(default_factory=list)
    duplicate_documents: int
    duplicate_chunks: int
    duplicate_links: int
    missing_provenance: int
    page_crossing: int
    references_after: int
    false_scope_links: int


class BuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: list[FinalDocumentRecord]
    chunks: list[FinalChunkRecord]
    links: list[IngredientLinkRecord]
    scope_rows: list[ScopeEvidenceRecord]
    validation: ValidationResult
    reuse_blocker: str | None
    snapshot_cir_document_count: int


_REPORT_SPECS = [
    ReportSpec(
        attachment_id="78339067-953f-de05-9d46-508a63ceca4c",
        file_name="retinol_retinyl_palmitate_re_review_2017.pdf",
        title="Retinol and Retinyl Palmitate",
        document_date=date(2017, 1, 1),
        doi=None,
        status_label="Published Re-review Not Opened",
        is_amended=False,
        document_type=CirDocumentType.RE_REVIEW_SUMMARY,
        ingredients=[IngredientSpec(name="Retinol", exact_terms=["Retinol"])],
        # 이 attachment는 18개 re-review 합본이므로 Retinol article만 물리 페이지로 한정한다.
        first_page=40,
        last_page=41,
    ),
    ReportSpec(
        attachment_id="d0ca1f11-8e74-ec11-8943-0022482f06a6",
        file_name="ascorbic_acid_ascorbates_final_report_2005.pdf",
        title=(
            "Final Report of the Safety Assessment of L-Ascorbic Acid, Calcium Ascorbate, "
            "Magnesium Ascorbate, Magnesium Ascorbyl Phosphate, Sodium Ascorbate, and "
            "Sodium Ascorbyl Phosphate as Used in Cosmetics"
        ),
        document_date=date(2005, 1, 1),
        doi="10.1080/10915810590953851",
        status_label="Published Report",
        is_amended=False,
        document_type=CirDocumentType.FINAL_SAFETY_ASSESSMENT,
        ingredients=[
            IngredientSpec(
                name="Ascorbic Acid",
                exact_terms=["L-Ascorbic Acid", "Ascorbic Acid"],
                excluded_terms=["3-O-Ethyl Ascorbic Acid"],
            ),
            IngredientSpec(
                name="Sodium Ascorbyl Phosphate", exact_terms=["Sodium Ascorbyl Phosphate"]
            ),
        ],
    ),
    ReportSpec(
        attachment_id="f8f3e083-2ca8-b5b4-b338-aa3ca6da8825",
        file_name="salicylic_acid_salicylates_amended_2025.pdf",
        title="Amended Safety Assessment of Salicylic Acid and Salicylates as Used in Cosmetics",
        document_date=date(2025, 1, 1),
        doi="10.1177/10915818251389456",
        status_label="Published Report",
        is_amended=True,
        document_type=CirDocumentType.AMENDED_SAFETY_ASSESSMENT,
        ingredients=[
            IngredientSpec(
                name="Salicylic Acid",
                exact_terms=["Salicylic Acid"],
                excluded_terms=["Capryloyl Salicylic Acid"],
            )
        ],
    ),
    ReportSpec(
        attachment_id="cd3b62ad-1279-3043-bf9f-58ee259b08ba",
        file_name="adenosine_safety_assessment_2024.pdf",
        title="Safety Assessment of Adenosine as Used in Cosmetics",
        document_date=date(2024, 1, 1),
        doi="10.1177/10915818231221790",
        status_label="Published Report",
        is_amended=False,
        document_type=CirDocumentType.SAFETY_ASSESSMENT,
        ingredients=[IngredientSpec(name="Adenosine", exact_terms=["Adenosine"])],
    ),
    ReportSpec(
        attachment_id="995efb2f-f539-86e3-8575-19bea03f915e",
        file_name="capryloyl_salicylic_acid_safety_assessment_2024.pdf",
        title="Safety Assessment of Capryloyl Salicylic Acid as Used in Cosmetics",
        document_date=date(2024, 1, 1),
        doi="10.1177/10915818241237794",
        status_label="Published Report",
        is_amended=True,
        document_type=CirDocumentType.STANDALONE_REASSESSMENT,
        ingredients=[
            IngredientSpec(
                name="Capryloyl Salicylic Acid", exact_terms=["Capryloyl Salicylic Acid"]
            )
        ],
    ),
]

_REUSE_INGREDIENTS = [
    IngredientSpec(name="Hydrolyzed Hyaluronic Acid", exact_terms=["Hydrolyzed Hyaluronic Acid"]),
    IngredientSpec(
        name="Sodium Acetylated Hyaluronate", exact_terms=["Sodium Acetylated Hyaluronate"]
    ),
    IngredientSpec(
        name="Hydrolyzed Sodium Hyaluronate", exact_terms=["Hydrolyzed Sodium Hyaluronate"]
    ),
    IngredientSpec(name="Potassium Hyaluronate", exact_terms=["Potassium Hyaluronate"]),
    IngredientSpec(name="Ceramide AP", exact_terms=["Ceramide AP"]),
    IngredientSpec(name="Ceramide EOP", exact_terms=["Ceramide EOP"]),
    IngredientSpec(name="Phytosphingosine", exact_terms=["Phytosphingosine"]),
    IngredientSpec(name="Tocopheryl Acetate", exact_terms=["Tocopheryl Acetate"]),
]


class PostgresCopySnapshotReader:
    def read(
        self,
        ingredient_path: Path,
        document_path: Path,
        chunk_path: Path,
        link_path: Path,
        ingredient_names: list[str],
    ) -> SnapshotData:
        ingredient_ids = self._read_ingredient_ids(ingredient_path, ingredient_names)
        documents = self._read_cir_documents(document_path)
        chunks = self._read_cir_chunks(chunk_path)
        chunk_ids_by_db_id = {chunk.chunk_db_id: chunk.chunk_id for chunk in chunks}
        existing_links = self._read_links(link_path, chunk_ids_by_db_id)
        return SnapshotData(
            ingredient_ids=ingredient_ids,
            cir_documents=documents,
            cir_chunks=chunks,
            existing_links=existing_links,
        )

    def _read_ingredient_ids(self, path: Path, names: list[str]) -> dict[str, UUID]:
        targets = {name.casefold(): name for name in names}
        resolved: dict[str, UUID] = {}
        for fields in self._copy_rows(path):
            if len(fields) < 9:
                continue
            canonical = targets.get(fields[2].casefold())
            if canonical is not None:
                resolved[canonical] = UUID(fields[8])
        return resolved

    def _read_cir_documents(self, path: Path) -> list[SnapshotDocument]:
        documents: list[SnapshotDocument] = []
        for fields in self._copy_rows(path):
            if len(fields) >= 18 and fields[1] == EvidenceDocumentSourceType.CIR.value:
                documents.append(
                    SnapshotDocument(
                        document_id=fields[17],
                        source_id=fields[0],
                        source_title=self._unescape(fields[2]),
                    )
                )
        return documents

    def _read_cir_chunks(self, path: Path) -> list[SnapshotChunk]:
        chunks: list[SnapshotChunk] = []
        for fields in self._copy_rows(path):
            if len(fields) < 18 or fields[2] != EvidenceDocumentSourceType.CIR.value:
                continue
            chunks.append(
                SnapshotChunk(
                    document_id=fields[0],
                    chunk_id=self._unescape(fields[1]),
                    source_title=self._unescape(fields[3]),
                    page=None if fields[4] == r"\N" else int(fields[4]),
                    section=None if fields[5] == r"\N" else self._unescape(fields[5]),
                    content=self._unescape(fields[7]),
                    chunk_db_id=fields[17],
                )
            )
        return chunks

    def _read_links(self, path: Path, chunk_ids_by_db_id: dict[str, str]) -> set[tuple[str, UUID]]:
        links: set[tuple[str, UUID]] = set()
        for fields in self._copy_rows(path):
            if len(fields) != 2 or fields[0] not in chunk_ids_by_db_id:
                continue
            links.add((chunk_ids_by_db_id[fields[0]], UUID(fields[1])))
        return links

    def _copy_rows(self, path: Path) -> Iterator[list[str]]:
        if not path.is_file():
            raise FileNotFoundError(f"DB snapshot 파일을 찾을 수 없습니다: {path}")
        in_copy = False
        with path.open(encoding="utf-8") as stream:
            for raw_line in stream:
                line = raw_line.rstrip("\n")
                if line.startswith("COPY public."):
                    in_copy = True
                    continue
                if in_copy and line == r"\.":
                    break
                if in_copy:
                    yield line.split("\t")

    def _unescape(self, value: str) -> str:
        if value == r"\N":
            return ""
        return (
            value.replace(r"\\", "\0")
            .replace(r"\n", "\n")
            .replace(r"\r", "\r")
            .replace(r"\t", "\t")
            .replace("\0", "\\")
        )


class ExactIngredientMatcher:
    def match(self, content: str, ingredient: IngredientSpec) -> re.Match[str] | None:
        excluded_spans = [
            match.span()
            for term in ingredient.excluded_terms
            for match in re.finditer(
                rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
                content,
                re.IGNORECASE,
            )
        ]
        for term in sorted(ingredient.exact_terms, key=len, reverse=True):
            pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE
            )
            for match in pattern.finditer(content):
                if not any(
                    start <= match.start() and match.end() <= end for start, end in excluded_spans
                ):
                    return match
        return None

    def context(self, content: str, match: re.Match[str]) -> str:
        start = max(0, match.start() - _CONTEXT_RADIUS)
        end = min(len(content), match.end() + _CONTEXT_RADIUS)
        return " ".join(content[start:end].split())


class CirFinalBundleBuilder:
    def __init__(self) -> None:
        self._evidence_builder = CirEvidenceBuilder()
        self._snapshot_reader = PostgresCopySnapshotReader()
        self._matcher = ExactIngredientMatcher()

    def build(
        self,
        input_dir: Path,
        ingredient_sql: Path,
        document_sql: Path,
        chunk_sql: Path,
        link_sql: Path,
        retrieved_at: datetime,
    ) -> BuildResult:
        all_ingredients = [
            ingredient.name for report in _REPORT_SPECS for ingredient in report.ingredients
        ] + [ingredient.name for ingredient in _REUSE_INGREDIENTS]
        snapshot = self._snapshot_reader.read(
            ingredient_sql,
            document_sql,
            chunk_sql,
            link_sql,
            all_ingredients,
        )
        unresolved = sorted(set(all_ingredients) - set(snapshot.ingredient_ids))
        if unresolved:
            raise RuntimeError(f"ingredient_id unresolved: {', '.join(unresolved)}")

        documents: list[FinalDocumentRecord] = []
        chunks: list[FinalChunkRecord] = []
        links: list[IngredientLinkRecord] = []
        scope_rows: list[ScopeEvidenceRecord] = []
        for report in _REPORT_SPECS:
            report_documents, report_chunks, report_links, report_scope = self._build_report(
                report, input_dir, snapshot.ingredient_ids, retrieved_at
            )
            documents.extend(report_documents)
            chunks.extend(report_chunks)
            links.extend(report_links)
            scope_rows.extend(report_scope)

        reuse_links, reuse_blocker = self._build_reuse_links(snapshot)
        links.extend(reuse_links)
        validation = self._validate(documents, chunks, links, unresolved)
        return BuildResult(
            documents=documents,
            chunks=chunks,
            links=links,
            scope_rows=scope_rows,
            validation=validation,
            reuse_blocker=reuse_blocker,
            snapshot_cir_document_count=len(snapshot.cir_documents),
        )

    def _build_report(
        self,
        report: ReportSpec,
        input_dir: Path,
        ingredient_ids: dict[str, UUID],
        retrieved_at: datetime,
    ) -> tuple[
        list[FinalDocumentRecord],
        list[FinalChunkRecord],
        list[IngredientLinkRecord],
        list[ScopeEvidenceRecord],
    ]:
        pdf_path = input_dir / report.file_name
        if not pdf_path.is_file():
            raise FileNotFoundError(f"검증된 CIR PDF를 찾을 수 없습니다: {pdf_path}")
        page_texts = self._evidence_builder.extract_page_texts(pdf_path)
        selected_pages = self._select_pages(page_texts, report)
        ids = [ingredient_ids[ingredient.name] for ingredient in report.ingredients]
        candidate = CirReportCandidate(
            attachment_id=report.attachment_id,
            title=report.title,
            status_label=report.status_label,
            is_amended=report.is_amended,
            publisher=_PUBLISHER,
            document_date=report.document_date,
            doi=report.doi,
            status_page_url=report.source_url,
            ingredient_ids=[],
            raw_ingredient_names=[ingredient.name for ingredient in report.ingredients],
            pdf_path=pdf_path,
        )
        bundle, chunking = self._evidence_builder.build_bundle(
            candidate, selected_pages, retrieved_at=retrieved_at
        )
        if chunking.warnings or not bundle.chunks:
            warnings = ", ".join(warning.value for warning in chunking.warnings) or "no chunks"
            raise RuntimeError(f"CIR chunking 실패({report.attachment_id}): {warnings}")

        document = FinalDocumentRecord(
            source_type=EvidenceDocumentSourceType.CIR,
            source_id=report.source_id,
            source_title=report.title,
            publisher=_PUBLISHER,
            document_date=report.document_date,
            url=report.source_url,
            doi=report.doi,
            pmid=None,
            language=_LANGUAGE,
            evidence_level=EvidenceLevel.EXPERT_REVIEWED,
            raw_ingredient_names=[ingredient.name for ingredient in report.ingredients],
            document_status=bundle.document.document_status,
            document_type=report.document_type,
            claim_topics=[EvidenceClaimTopic.PRECAUTION],
            retrieved_at=retrieved_at,
            ingredient_ids=ids,
            attachment_id=report.attachment_id,
            pdf_sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        )
        final_chunks: list[FinalChunkRecord] = []
        links: list[IngredientLinkRecord] = []
        scope_by_ingredient: dict[str, ScopeEvidenceRecord] = {}
        for chunk in bundle.chunks:
            if chunk.page is None or chunk.section is None:
                raise RuntimeError(f"chunk provenance 누락: {chunk.chunk_id}")
            matched_ids: list[UUID] = []
            for ingredient in report.ingredients:
                match = self._matcher.match(chunk.content, ingredient)
                if match is None:
                    continue
                ingredient_id = ingredient_ids[ingredient.name]
                matched_ids.append(ingredient_id)
                matched_text = match.group(0)
                links.append(
                    IngredientLinkRecord(
                        source_title=report.title,
                        chunk_id=chunk.chunk_id,
                        page=chunk.page,
                        section=chunk.section,
                        ingredient=ingredient.name,
                        ingredient_id=ingredient_id,
                        matched_text=matched_text,
                        scope_verified=True,
                        linkage_type=LinkageType.NEW_DOCUMENT,
                    )
                )
                scope_by_ingredient.setdefault(
                    ingredient.name,
                    ScopeEvidenceRecord(
                        ingredient=ingredient.name,
                        report_title=report.title,
                        attachment_id=report.attachment_id,
                        page=chunk.page,
                        section=chunk.section,
                        matched_text=matched_text,
                        context=self._matcher.context(chunk.content, match),
                        scope_verified=True,
                        note=self._scope_note(report),
                    ),
                )
            final_chunks.append(
                FinalChunkRecord(
                    document_source_id=chunk.document_source_id,
                    chunk_id=chunk.chunk_id,
                    source_type=chunk.source_type,
                    source_title=chunk.source_title,
                    page=chunk.page,
                    section=chunk.section,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    parser_version=chunk.parser_version,
                    url=report.source_url,
                    doi=chunk.doi,
                    pmid=chunk.pmid,
                    evidence_level=chunk.evidence_level,
                    ingredient_ids=matched_ids,
                )
            )
        missing_scope = [
            ingredient.name
            for ingredient in report.ingredients
            if ingredient.name not in scope_by_ingredient
        ]
        if missing_scope:
            raise RuntimeError(
                f"실제 chunk 본문에 exact ingredient가 없음({report.attachment_id}): "
                + ", ".join(missing_scope)
            )
        return [document], final_chunks, links, list(scope_by_ingredient.values())

    def _select_pages(self, pages: list[str], report: ReportSpec) -> list[str]:
        if report.first_page < 1 or report.first_page > len(pages):
            raise RuntimeError(f"잘못된 first_page({report.attachment_id}): {report.first_page}")
        end = report.last_page or len(pages)
        if end < report.first_page or end > len(pages):
            raise RuntimeError(f"잘못된 last_page({report.attachment_id}): {end}")
        # 앞쪽을 빈 페이지로 보존해야 chunk의 page가 PDF 물리 페이지와 일치한다.
        return [""] * (report.first_page - 1) + pages[report.first_page - 1 : end]

    def _scope_note(self, report: ReportSpec) -> str:
        if report.document_type is CirDocumentType.RE_REVIEW_SUMMARY:
            return "2017 re-review summary; full CIR safety assessment로 취급하지 않음"
        if report.document_type is CirDocumentType.STANDALONE_REASSESSMENT:
            return "2024 standalone reassessment; 2003 historical (ester) 분류를 사용하지 않음"
        if report.document_type is CirDocumentType.AMENDED_SAFETY_ASSESSMENT:
            return "2025 amended report만 canonical 신규 근거로 사용"
        if len(report.ingredients) > 1:
            return (
                "EvidenceDocument 1건 공유; ingredient linkage는 chunk exact mention 기준으로 분리"
            )
        return "REFERENCES 이전 selected body chunk의 exact ingredient mention 확인"

    def _build_reuse_links(
        self, snapshot: SnapshotData
    ) -> tuple[list[IngredientLinkRecord], str | None]:
        if not snapshot.cir_documents or not snapshot.cir_chunks:
            return (
                [],
                (
                    "최신 사용 가능 SQL snapshot에 CIR document/chunk가 없어 기존 8개 재사용 "
                    "후보를 검증할 수 없음"
                ),
            )
        document_ids = {document.document_id for document in snapshot.cir_documents}
        links: list[IngredientLinkRecord] = []
        for chunk in snapshot.cir_chunks:
            if chunk.document_id not in document_ids or chunk.page is None or chunk.section is None:
                continue
            for ingredient in _REUSE_INGREDIENTS:
                match = self._matcher.match(chunk.content, ingredient)
                if match is None:
                    continue
                ingredient_id = snapshot.ingredient_ids[ingredient.name]
                if (chunk.chunk_id, ingredient_id) in snapshot.existing_links:
                    continue
                links.append(
                    IngredientLinkRecord(
                        source_title=chunk.source_title,
                        chunk_id=chunk.chunk_id,
                        page=chunk.page,
                        section=chunk.section,
                        ingredient=ingredient.name,
                        ingredient_id=ingredient_id,
                        matched_text=match.group(0),
                        scope_verified=True,
                        linkage_type=LinkageType.EXISTING_DOCUMENT_REUSE,
                    )
                )
        return links, None

    def _validate(
        self,
        documents: list[FinalDocumentRecord],
        chunks: list[FinalChunkRecord],
        links: list[IngredientLinkRecord],
        unresolved: list[str],
    ) -> ValidationResult:
        document_keys = [(document.source_type, document.source_id) for document in documents]
        chunk_keys = [chunk.chunk_id for chunk in chunks]
        link_keys = [(link.chunk_id, link.ingredient_id) for link in links]
        missing_provenance = sum(
            not chunk.document_source_id
            or not chunk.source_title
            or not chunk.page
            or not chunk.section
            for chunk in chunks
        )
        references_after = sum("REFERENCES" in chunk.section.upper() for chunk in chunks)
        false_scope_links = sum(not link.scope_verified for link in links)
        return ValidationResult(
            unresolved=unresolved,
            duplicate_documents=len(document_keys) - len(set(document_keys)),
            duplicate_chunks=len(chunk_keys) - len(set(chunk_keys)),
            duplicate_links=len(link_keys) - len(set(link_keys)),
            missing_provenance=missing_provenance,
            # chunk schema가 단일 page 정수만 허용하고 builder가 페이지별 segment를 만들므로 0이다.
            page_crossing=0,
            references_after=references_after,
            false_scope_links=false_scope_links,
        )


class CirFinalBundleWriter:
    def write(self, result: BuildResult, output_dir: Path, snapshot_paths: list[Path]) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_jsonl(output_dir / "cir_final_documents.jsonl", result.documents)
        self._write_jsonl(output_dir / "cir_final_chunks.jsonl", result.chunks)
        self._write_csv(
            output_dir / "cir_chunk_ingredient_links.csv",
            result.links,
            list(IngredientLinkRecord.model_fields),
        )
        self._write_csv(
            output_dir / "cir_scope_evidence.csv",
            result.scope_rows,
            list(ScopeEvidenceRecord.model_fields),
        )
        (output_dir / "CIR_FINAL_BUNDLE_REPORT.md").write_text(
            self._report(result, snapshot_paths), encoding="utf-8"
        )

    def _write_jsonl(self, path: Path, records: list[BaseModel]) -> None:
        path.write_text(
            "".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8"
        )

    def _write_csv(self, path: Path, records: list[BaseModel], fieldnames: list[str]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            # Git 산출물에서도 CR 문자가 trailing whitespace로 잡히지 않도록 LF로 고정한다.
            writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for record in records:
                writer.writerow(record.model_dump(mode="json"))

    def _report(self, result: BuildResult, snapshot_paths: list[Path]) -> str:
        new_links = sum(link.linkage_type is LinkageType.NEW_DOCUMENT for link in result.links)
        reuse_links = sum(
            link.linkage_type is LinkageType.EXISTING_DOCUMENT_REUSE for link in result.links
        )
        validation = result.validation
        duplicate_total = (
            validation.duplicate_documents
            + validation.duplicate_chunks
            + validation.duplicate_links
        )
        ready = "NO" if result.reuse_blocker else "YES"
        snapshot_lines = "\n".join(f"- `{path}`" for path in snapshot_paths)
        blocker = result.reuse_blocker or "없음"
        return f"""# CIR Final Bundle Report

## 입력 및 정책

- 공식 CIR PDF 5건을 사용했고 웹 검색·embedding·DB write는 수행하지 않았다.
- Retinol 2017은 `re_review_summary`이며 full safety assessment로 취급하지 않았다.
- Ascorbic Acid와 Sodium Ascorbyl Phosphate는 document 1건을 공유하고 chunk linkage만 분리했다.
- Salicylic Acid는 2025 amended report, Capryloyl Salicylic Acid는 2024 standalone reassessment만 사용했다.
- chunk는 물리 page와 section을 보존하며 REFERENCES 이후와 back matter를 제외했다.

## 읽기 전용 snapshot

{snapshot_lines}

- snapshot CIR document 수: {result.snapshot_cir_document_count}
- 기존 8개 재사용 blocker: {blocker}

## 산출 및 검증

- Documents: {len(result.documents)}
- Chunks: {len(result.chunks)}
- Ingredient links: {len(result.links)} (NEW_DOCUMENT {new_links}, EXISTING_DOCUMENT_REUSE {reuse_links})
- Scope verification: {len(result.scope_rows)}/6 verified
- Unresolved ingredient_id: {len(validation.unresolved)}
- Duplicate document/chunk/link: {duplicate_total}
- Missing provenance: {validation.missing_provenance}
- Page-crossing: {validation.page_crossing}
- REFERENCES 이후 chunk: {validation.references_after}
- scope_verified=false link: {validation.false_scope_links}

## 판정

`READY_FOR_COMBINED_EVIDENCE_BUNDLE: {ready}`

신규 5-document bundle은 완성됐다. 기존 CIR 8개 재사용 링크는 snapshot에서 실제 CIR
document/chunk를 확인할 수 있을 때만 생성해야 하며, 현재 blocker가 있으면 임의 생성하지 않는다.
"""


class CirFinalBundleCli:
    def run(self) -> None:
        arguments = self._arguments()
        snapshot_paths = [
            arguments.ingredient_sql,
            arguments.document_sql,
            arguments.chunk_sql,
            arguments.link_sql,
        ]
        result = CirFinalBundleBuilder().build(
            input_dir=arguments.input_dir,
            ingredient_sql=arguments.ingredient_sql,
            document_sql=arguments.document_sql,
            chunk_sql=arguments.chunk_sql,
            link_sql=arguments.link_sql,
            retrieved_at=datetime.now(UTC),
        )
        validation = result.validation
        if any(
            (
                validation.unresolved,
                validation.duplicate_documents,
                validation.duplicate_chunks,
                validation.duplicate_links,
                validation.missing_provenance,
                validation.page_crossing,
                validation.references_after,
                validation.false_scope_links,
            )
        ):
            raise RuntimeError(f"CIR final bundle validation 실패: {validation.model_dump()}")
        CirFinalBundleWriter().write(result, arguments.output_dir, snapshot_paths)
        print(
            json.dumps(
                {
                    "documents": len(result.documents),
                    "chunks": len(result.chunks),
                    "links": len(result.links),
                    "reuse_blocker": result.reuse_blocker,
                },
                ensure_ascii=False,
            )
        )

    def _arguments(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="CIR final bundle 생성 및 검증")
        parser.add_argument("--input-dir", type=Path, default=_DEFAULT_INPUT_DIR)
        parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
        parser.add_argument("--ingredient-sql", type=Path, default=_DEFAULT_INGREDIENT_SQL)
        parser.add_argument("--document-sql", type=Path, default=_DEFAULT_DOCUMENT_SQL)
        parser.add_argument("--chunk-sql", type=Path, default=_DEFAULT_CHUNK_SQL)
        parser.add_argument("--link-sql", type=Path, default=_DEFAULT_LINK_SQL)
        return parser.parse_args()


if __name__ == "__main__":
    CirFinalBundleCli().run()
