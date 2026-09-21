"""CIR report PDF 텍스트를 section-aware · page-aware chunk 로 나누고 document draft 를 만든다.

원문 전체는 보존하되 임베딩은 핵심 section 만 한다. 요약하지 않고 원문 span 만 쓰며,
어떤 chunk 도 page 경계를 넘지 않는다(그래야 citation 의 page 가 정확하다).

section 제목은 어휘가 보고서마다 달라 고정 목록 대신 "짧은 전체 대문자 단독 줄" 규칙으로
감지한다(`CIR_PDF_INGESTION_FEASIBILITY.md` 7절). 러닝 헤더/푸터는 여러 페이지에 반복되므로
숫자를 지운 형태가 3페이지 이상에 나오는 줄을 노이즈로 걸러낸다.
"""

import hashlib
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pdfplumber
from pdfplumber.page import Page

from data.scripts.cir_report_selector import CirReportSelector
from data.scripts.evidence_collector_schemas import (
    CirChunkingResult,
    CirChunkingWarning,
    CirReportCandidate,
    EvidenceBundle,
    EvidenceChunkDraft,
    EvidenceDocumentDraft,
)
from models.evidence_document import (
    EvidenceClaimTopic,
    EvidenceDocumentSourceType,
    EvidenceLevel,
)

CIR_PARSER_VERSION = "cir-pdf-section-v1"
_SOURCE_ID_PREFIX = "cir_attachment"
_CIR_LANGUAGE = "en"

# 임베딩 우선 section. 실제 문서에서 감지된 heading 에 이 키워드가 들어 있을 때만 쓴다
# (예: "CLINICAL ASSESSMENT OF SAFETY" 는 CLINICAL 로 잡힌다).
_TARGET_SECTION_KEYWORDS = ("CLINICAL", "SAFETY ASSESSMENT", "DISCUSSION", "CONCLUSION")
# 이 heading 이후는 인용 목록이라 검색 대상이 아니다
_TERMINAL_SECTION_KEYWORD = "REFERENCES"

_HEADING_PATTERN = re.compile(r"[A-Z][A-Z ,&/\-]{3,49}")
_NON_HEADING_PREFIXES = ("TABLE", "FIGURE")
_DIGIT_PATTERN = re.compile(r"\d+")
_RUNNING_HEADER_MIN_PAGES = 3
_RUNNING_HEADER_MAX_LENGTH = 100

# pdfplumber 기본값(3)은 이 보고서에서 단어 사이 공백을 잃는다(실측). 1 이 공백을 복원한다.
_WORD_X_TOLERANCE = 1
_TWO_COLUMN_MAX_CROSSING_RATIO = 0.02

# 한 (page, section) 조각이 이보다 길 때만 문단 경계에서 나눈다. bge-m3 입력 한도(8192 토큰)
# 안에 넉넉히 들어오는 크기다.
MAX_CHUNK_CHARS = 3000
_SENTENCE_END = (".", "!", "?")


class CirSectionChunker:
    def chunk(
        self, page_texts: list[str], *, candidate: CirReportCandidate, source_id: str
    ) -> CirChunkingResult:
        running_headers = self._running_headers(page_texts)
        segments, detected = self._segment(page_texts, running_headers)

        warnings: list[CirChunkingWarning] = []
        if not detected:
            warnings.append(CirChunkingWarning.NO_SECTIONS_DETECTED)
        elif not any(self._is_target(section) for section in detected):
            warnings.append(CirChunkingWarning.NO_TARGET_SECTIONS)

        chunks: list[EvidenceChunkDraft] = []
        for page, section, text in segments:
            if section is None or not self._is_target(section):
                continue
            for piece in self._split_long(text):
                chunks.append(
                    self._build_chunk(candidate, source_id, page, section, len(chunks), piece)
                )
        return CirChunkingResult(detected_sections=detected, chunks=chunks, warnings=warnings)

    def _running_headers(self, page_texts: list[str]) -> set[str]:
        pages_by_normalized_line: Counter[str] = Counter()
        for text in page_texts:
            normalized_on_page = {
                self._normalize_line(line)
                for line in text.splitlines()
                if line.strip() and len(line.strip()) <= _RUNNING_HEADER_MAX_LENGTH
            }
            pages_by_normalized_line.update(normalized_on_page)
        return {
            line
            for line, page_count in pages_by_normalized_line.items()
            if page_count >= _RUNNING_HEADER_MIN_PAGES
        }

    def _normalize_line(self, line: str) -> str:
        return _DIGIT_PATTERN.sub("#", line.strip())

    def _segment(
        self, page_texts: list[str], running_headers: set[str]
    ) -> tuple[list[tuple[int, str | None, str]], list[str]]:
        """페이지 순서대로 (page, section, text) 조각을 만든다.

        heading 은 페이지 중간에도 나올 수 있어 줄 단위로 section 을 갱신한다. section 은 다음
        heading 까지 페이지를 넘어 이어지지만, 조각(text)은 항상 한 페이지 안에서만 만든다.
        """
        segments: list[tuple[int, str | None, str]] = []
        detected: list[str] = []
        current: str | None = None
        for page_number, text in enumerate(page_texts, start=1):
            buffer: list[str] = []
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or self._normalize_line(line) in running_headers:
                    continue
                if self._is_heading(line):
                    self._flush(segments, page_number, current, buffer)
                    buffer = []
                    current = line
                    detected.append(line)
                    continue
                buffer.append(line)
            self._flush(segments, page_number, current, buffer)
            if current is not None and _TERMINAL_SECTION_KEYWORD in current:
                break
        return segments, detected

    def _flush(
        self,
        segments: list[tuple[int, str | None, str]],
        page: int,
        section: str | None,
        buffer: list[str],
    ) -> None:
        if buffer:
            segments.append((page, section, "\n".join(buffer)))

    def _is_heading(self, line: str) -> bool:
        return bool(_HEADING_PATTERN.fullmatch(line)) and not line.startswith(_NON_HEADING_PREFIXES)

    def _is_target(self, section: str) -> bool:
        return any(keyword in section for keyword in _TARGET_SECTION_KEYWORDS)

    def _split_long(self, text: str) -> list[str]:
        if len(text) <= MAX_CHUNK_CHARS:
            return [text]
        pieces: list[str] = []
        current: list[str] = []
        current_length = 0
        for line in text.splitlines():
            current.append(line)
            current_length += len(line) + 1
            # 문장 중간을 자르지 않도록 문장 끝에서만 나눈다
            if current_length >= MAX_CHUNK_CHARS and line.endswith(_SENTENCE_END):
                pieces.append("\n".join(current))
                current, current_length = [], 0
        if current:
            pieces.append("\n".join(current))
        return pieces

    def _build_chunk(
        self,
        candidate: CirReportCandidate,
        source_id: str,
        page: int,
        section: str,
        chunk_index: int,
        content: str,
    ) -> EvidenceChunkDraft:
        return EvidenceChunkDraft(
            document_source_id=source_id,
            chunk_id=f"{source_id}:{page}:{section}:{chunk_index}",
            source_type=EvidenceDocumentSourceType.CIR,
            source_title=candidate.title,
            page=page,
            section=section,
            chunk_index=chunk_index,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            parser_version=CIR_PARSER_VERSION,
            url=candidate.status_page_url,
            doi=candidate.doi,
            pmid=None,
            evidence_level=EvidenceLevel.EXPERT_REVIEWED,
            ingredient_ids=candidate.ingredient_ids,
        )


class CirPdfTextExtractor:
    """PDF 페이지를 읽는 순서대로의 텍스트로 뽑는다.

    pdfplumber 는 좌·우 컬럼을 같은 y 줄로 섞어 읽으므로(실측: REFERENCES heading 이 왼쪽 컬럼
    줄 끝에 붙음) 2단 페이지는 컬럼별로 따로 뽑아 이어 붙인다. 컬럼 판정은 가운데 선을 걸치는 단어
    비율로 한다 - 표·제목처럼 전폭인 페이지는 걸치는 단어가 많아 단일 컬럼으로 처리된다.
    """

    def extract(self, pdf_path: Path) -> list[str]:
        """페이지 번호를 보존하기 위해 빈 페이지도 자리를 유지한다(index+1 = 물리 페이지)."""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                return [self.extract_page(page) for page in pdf.pages]
        except (OSError, ValueError) as e:
            raise RuntimeError(f"CIR PDF 텍스트 추출 실패({pdf_path}): {e}") from e

    def extract_page(self, page: Page) -> str:
        words = page.extract_words(x_tolerance=_WORD_X_TOLERANCE)
        middle = page.width / 2
        crossing = sum(1 for word in words if word["x0"] < middle < word["x1"])
        if words and crossing / len(words) <= _TWO_COLUMN_MAX_CROSSING_RATIO:
            left = page.within_bbox((0, 0, middle, page.height))
            right = page.within_bbox((middle, 0, page.width, page.height))
            return "\n".join(
                column.extract_text(x_tolerance=_WORD_X_TOLERANCE) or "" for column in (left, right)
            )
        return page.extract_text(x_tolerance=_WORD_X_TOLERANCE) or ""


class CirEvidenceBuilder:
    def __init__(
        self,
        selector: CirReportSelector | None = None,
        chunker: CirSectionChunker | None = None,
        extractor: CirPdfTextExtractor | None = None,
    ) -> None:
        self._selector = selector or CirReportSelector()
        self._chunker = chunker or CirSectionChunker()
        self._extractor = extractor or CirPdfTextExtractor()

    def build_source_id(self, attachment_id: str) -> str:
        return f"{_SOURCE_ID_PREFIX}:{attachment_id}"

    def extract_page_texts(self, pdf_path: Path) -> list[str]:
        return self._extractor.extract(pdf_path)

    def build_bundle(
        self, candidate: CirReportCandidate, page_texts: list[str], *, retrieved_at: datetime
    ) -> tuple[EvidenceBundle, CirChunkingResult]:
        source_id = self.build_source_id(candidate.attachment_id)
        result = self._chunker.chunk(page_texts, candidate=candidate, source_id=source_id)
        document = EvidenceDocumentDraft(
            source_type=EvidenceDocumentSourceType.CIR,
            source_id=source_id,
            source_title=candidate.title,
            publisher=candidate.publisher,
            document_date=candidate.document_date,
            url=candidate.status_page_url,
            doi=candidate.doi,
            pmid=None,
            language=_CIR_LANGUAGE,
            evidence_level=EvidenceLevel.EXPERT_REVIEWED,
            raw_ingredient_names=candidate.raw_ingredient_names,
            document_status=self._selector.map_status(candidate),
            study_type=None,
            formulation_type=None,
            claim_topics=[EvidenceClaimTopic.PRECAUTION],
            retrieved_at=retrieved_at,
            ingredient_ids=candidate.ingredient_ids,
        )
        return EvidenceBundle(document=document, chunks=result.chunks), result
