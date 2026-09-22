"""CIR report 선택·section-aware chunking 단위 테스트. PDF/네트워크 없이 페이지 텍스트 fixture 만 쓴다."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from data.scripts.cir_evidence_builder import (
    CIR_PARSER_VERSION,
    MAX_CHUNK_CHARS,
    CirEvidenceBuilder,
    CirPdfTextExtractor,
    CirSectionChunker,
)
from data.scripts.cir_report_selector import CirReportSelector
from data.scripts.evidence_collector_schemas import CirChunkingWarning, CirReportCandidate
from models.evidence_document import (
    EvidenceDocumentSourceType,
    EvidenceDocumentStatus,
    EvidenceLevel,
)

_NIA = UUID("00000000-0000-0000-0000-00000000000a")
_RETINOL = UUID("00000000-0000-0000-0000-00000000000b")
_NOW = datetime(2026, 9, 21, tzinfo=UTC)


def _report(
    attachment_id: str,
    ingredient_ids: list[UUID],
    *,
    status_label: str = "Published Report",
    on: date | None = date(2005, 1, 1),
    is_amended: bool = False,
) -> CirReportCandidate:
    return CirReportCandidate(
        attachment_id=attachment_id,
        title=f"report {attachment_id}",
        status_label=status_label,
        is_amended=is_amended,
        document_date=on,
        ingredient_ids=ingredient_ids,
        status_page_url="https://cir-reports.cir-safety.org/status?id=x",
    )


class TestSelector:
    def test_picks_latest_among_multiple_historical_reports(self) -> None:
        reports = [
            _report("old", [_NIA], on=date(2003, 1, 1)),
            _report("new", [_NIA], on=date(2025, 1, 1), is_amended=True),
            _report("mid", [_NIA], on=date(2014, 1, 1)),
        ]
        (selected,) = CirReportSelector().select(reports, [_NIA])
        assert selected.attachment_id == "new"

    def test_amended_wins_same_date_tie(self) -> None:
        reports = [
            _report("a", [_NIA], is_amended=False),
            _report("b", [_NIA], is_amended=True),
        ]
        (selected,) = CirReportSelector().select(reports, [_NIA])
        assert selected.attachment_id == "b"

    def test_rereview_not_opened_is_never_selected(self) -> None:
        reports = [
            _report("1987", [_RETINOL], on=date(1987, 1, 1)),
            _report(
                "2017",
                [_RETINOL],
                status_label="Published Re-review Not Opened",
                on=date(2017, 1, 1),
            ),
        ]
        (selected,) = CirReportSelector().select(reports, [_RETINOL])
        assert selected.attachment_id == "1987"

    def test_draft_tentative_unknown_are_not_authoritative(self) -> None:
        reports = [
            _report("d", [_NIA], status_label="Draft Report"),
            _report("t", [_NIA], status_label="Tentative Report"),
            _report("u", [_NIA], status_label="Something else"),
        ]
        assert CirReportSelector().select(reports, [_NIA]) == []

    def test_status_mapping(self) -> None:
        selector = CirReportSelector()
        assert selector.map_status(_report("a", [_NIA])) is EvidenceDocumentStatus.FINAL
        assert (
            selector.map_status(_report("a", [_NIA], is_amended=True))
            is EvidenceDocumentStatus.AMENDED_FINAL
        )
        assert (
            selector.map_status(_report("a", [_NIA], status_label="Published Re-review Not Opened"))
            is EvidenceDocumentStatus.REREVIEW
        )

    def test_final_report_label_is_authoritative(self) -> None:
        # 실측: 2023년 Hyaluronates report 는 "Published Report"가 아니라 "Final Report" 라벨이다
        report = _report("hyal", [_NIA], status_label="Final Report")
        assert CirReportSelector().map_status(report) is EvidenceDocumentStatus.FINAL
        assert len(CirReportSelector().select([report], [_NIA])) == 1

    def test_group_review_is_one_document_linked_to_all_requested_ingredients(self) -> None:
        group = _report("group", [_NIA, _RETINOL, uuid4()])
        selected = CirReportSelector().select([group], [_NIA, _RETINOL])
        assert len(selected) == 1
        # 요청하지 않은 성분은 연결하지 않는다
        assert selected[0].ingredient_ids == [_NIA, _RETINOL]

    def test_only_requested_ingredients_are_selected(self) -> None:
        reports = [_report("nia", [_NIA]), _report("ret", [_RETINOL])]
        selected = CirReportSelector().select(reports, [_NIA])
        assert [r.attachment_id for r in selected] == ["nia"]

    def test_ingredient_without_report_yields_nothing(self) -> None:
        assert CirReportSelector().select([_report("nia", [_NIA])], [_RETINOL]) == []


_RUNNING = "SAFETY ASSESSMENT OF NIACINAMIDE {n}"
_HEADER = "{n} COSMETIC INGREDIENT REVIEW"


def _pages() -> list[str]:
    return [
        f"{_HEADER.format(n=1)}\nINTRODUCTION\nIntro text on page one.\nCHEMISTRY\nChemistry text.",
        f"{_RUNNING.format(n=2)}\nMore chemistry that must not be embedded.",
        (
            f"{_HEADER.format(n=3)}\nTABLE 2\nrow data\nCLINICAL ASSESSMENT OF SAFETY\n"
            "Clinical text on page three."
        ),
        f"{_RUNNING.format(n=4)}\nClinical text continues on page four.",
        (
            f"{_HEADER.format(n=5)}\nEnd of clinical part.\nDISCUSSION\nDiscussion text.\n"
            "CONCLUSION\nConclusion text."
        ),
        f"{_RUNNING.format(n=6)}\nConclusion continues.\nREFERENCES\n1. Some citation.",
        f"{_HEADER.format(n=7)}\n2. Another citation that must be ignored.",
    ]


def _chunk(pages: list[str]):
    report = _report("att-1", [_NIA])
    return CirSectionChunker().chunk(pages, candidate=report, source_id="cir_attachment:att-1")


class TestChunker:
    def test_only_target_sections_are_embedded_and_references_excluded(self) -> None:
        result = _chunk(_pages())
        assert {c.section for c in result.chunks} == {
            "CLINICAL ASSESSMENT OF SAFETY",
            "DISCUSSION",
            "CONCLUSION",
        }
        joined = "\n".join(c.content for c in result.chunks)
        assert "Intro text" not in joined and "Chemistry" not in joined
        assert "citation" not in joined.lower()
        assert "REFERENCES" in result.detected_sections

    def test_page_and_section_provenance_preserved(self) -> None:
        result = _chunk(_pages())
        by_key = {(c.page, c.section): c for c in result.chunks}
        clinical_p3 = by_key[(3, "CLINICAL ASSESSMENT OF SAFETY")]
        assert clinical_p3.content == "Clinical text on page three."
        assert clinical_p3.source_type is EvidenceDocumentSourceType.CIR
        assert clinical_p3.evidence_level is EvidenceLevel.EXPERT_REVIEWED
        assert clinical_p3.document_source_id == "cir_attachment:att-1"
        assert clinical_p3.source_title == "report att-1"
        assert clinical_p3.url == "https://cir-reports.cir-safety.org/status?id=x"
        assert clinical_p3.parser_version == CIR_PARSER_VERSION
        assert len(clinical_p3.content_hash) == 64
        assert clinical_p3.chunk_id == (
            f"cir_attachment:att-1:3:CLINICAL ASSESSMENT OF SAFETY:{clinical_p3.chunk_index}"
        )

    def test_section_carries_across_pages_but_chunks_never_cross_pages(self) -> None:
        result = _chunk(_pages())
        pages = [(c.page, c.section) for c in result.chunks]
        # 4쪽은 heading 이 없지만 이전 section 을 이어받아 별도 chunk 로 남는다
        assert (4, "CLINICAL ASSESSMENT OF SAFETY") in pages
        assert (3, "CLINICAL ASSESSMENT OF SAFETY") in pages
        for chunk in result.chunks:
            assert "page three" not in chunk.content or chunk.page == 3
            assert "page four" not in chunk.content or chunk.page == 4

    def test_heading_mid_page_splits_section_boundary(self) -> None:
        result = _chunk(_pages())
        page5 = {c.section: c.content for c in result.chunks if c.page == 5}
        assert page5["CLINICAL ASSESSMENT OF SAFETY"] == "End of clinical part."
        assert page5["DISCUSSION"] == "Discussion text."
        assert page5["CONCLUSION"] == "Conclusion text."

    def test_running_headers_and_table_captions_are_not_sections(self) -> None:
        result = _chunk(_pages())
        assert not any(
            "COSMETIC INGREDIENT" in s or "SAFETY ASSESSMENT OF" in s
            for s in result.detected_sections
        )
        assert "TABLE 2" not in result.detected_sections

    def test_chunk_indexes_are_sequential(self) -> None:
        result = _chunk(_pages())
        assert [c.chunk_index for c in result.chunks] == list(range(len(result.chunks)))

    def test_long_section_splits_at_sentence_boundary_within_page(self) -> None:
        sentence = "x" * 400 + "."
        long_page = "CONCLUSION\n" + "\n".join([sentence] * 20)
        result = _chunk([long_page])
        assert len(result.chunks) > 1
        assert all(c.page == 1 for c in result.chunks)
        assert all(c.content.endswith(".") for c in result.chunks)
        assert all(len(c.content) < MAX_CHUNK_CHARS + len(sentence) + 1 for c in result.chunks)

    def test_title_case_headings_and_references_cutoff(self) -> None:
        # 2009년 이후 서식: heading 이 Title Case. References 이후는 chunk 에 섞이면 안 된다
        pages = [
            "Summary\nsummary text",
            "Clinical Assessment of Safety\nclinical text\nDiscussion\ndiscussion text",
            "Conclusion\nconclusion text\nReferences\n1. Smith 2001 citation",
            "2. Jones 2002 more citations",
        ]
        result = _chunk(pages)
        assert [(c.page, c.section) for c in result.chunks] == [
            (2, "Clinical Assessment of Safety"),
            (2, "Discussion"),
            (3, "Conclusion"),
        ]
        assert not any("citation" in c.content for c in result.chunks)

    def test_back_matter_is_not_folded_into_conclusion(self) -> None:
        result = _chunk(
            [
                (
                    "Conclusion\nThe ingredient is safe.\n"
                    "Declaration of Conflicting Interests\nNo conflicts.\n"
                    "Funding\nCIR funded this report.\nReferences\n1. Citation"
                )
            ]
        )
        assert [c.content for c in result.chunks] == ["The ingredient is safe."]

    def test_singular_reference_label_is_not_a_heading(self) -> None:
        result = _chunk(["Conclusion\nReference\nstill conclusion body"])
        assert "Reference" in result.chunks[0].content

    def test_table_caption_ends_body_and_numbered_citation_page_is_dropped(self) -> None:
        # 최신 서식: Conclusion 뒤에 "Table 1." 표가 붙는다. References heading 이 없어도
        # 번호 인용이 빽빽한 페이지는 인용 목록으로 보고 제외한다
        citations = "\n".join(f"{n}. Author AB. Title {n}." for n in range(1, 8))
        pages = ["Conclusion\nsafe.\nTABLES\nTable 1. Definitions\nrow", citations]
        result = _chunk(pages)
        assert [c.content for c in result.chunks] == ["safe."]

    def test_no_headings_yields_warning_and_no_chunks(self) -> None:
        result = _chunk(["plain paragraph without headings.", "another page."])
        assert result.chunks == []
        assert result.warnings == [CirChunkingWarning.NO_SECTIONS_DETECTED]

    def test_only_non_target_headings_yields_warning(self) -> None:
        result = _chunk(["INTRODUCTION\ntext", "CHEMISTRY\ntext"])
        assert result.chunks == []
        assert result.warnings == [CirChunkingWarning.NO_TARGET_SECTIONS]

    def test_empty_pages_keep_page_numbers(self) -> None:
        result = _chunk(["", "", "CONCLUSION\nfinal words."])
        assert [c.page for c in result.chunks] == [3]


class TestBuilder:
    def test_bundle_document_maps_report_metadata(self) -> None:
        report = _report("att-9", [_NIA, _RETINOL], is_amended=True).model_copy(
            update={"publisher": "International Journal of Toxicology", "doi": "10.1080/x"}
        )
        bundle, result = CirEvidenceBuilder().build_bundle(report, _pages(), retrieved_at=_NOW)
        document = bundle.document
        assert document.source_id == "cir_attachment:att-9"
        assert document.source_type is EvidenceDocumentSourceType.CIR
        assert document.evidence_level is EvidenceLevel.EXPERT_REVIEWED
        assert document.document_status is EvidenceDocumentStatus.AMENDED_FINAL
        assert document.ingredient_ids == [_NIA, _RETINOL]
        assert document.study_type is None and document.formulation_type is None
        assert document.doi == "10.1080/x" and document.pmid is None
        assert bundle.chunks == result.chunks
        assert all(c.ingredient_ids == [_NIA, _RETINOL] for c in bundle.chunks)


class _StubColumn:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self, **_: object) -> str:
        return self._text


class _StubPage:
    """pdfplumber Page 대역. 왼쪽 bbox(x0=0)와 오른쪽 bbox 에 서로 다른 텍스트를 돌려준다."""

    width = 600
    height = 800

    def __init__(self, words: list[dict[str, float]], left: str, right: str, full: str) -> None:
        self._words = words
        self._columns = {True: _StubColumn(left), False: _StubColumn(right)}
        self._full = full

    def extract_words(self, **_: object) -> list[dict[str, float]]:
        return self._words

    def within_bbox(self, bbox: tuple[float, float, float, float]) -> _StubColumn:
        return self._columns[bbox[0] == 0]

    def extract_text(self, **_: object) -> str:
        return self._full


class TestPdfTextExtractor:
    def test_two_column_page_reads_left_column_then_right(self) -> None:
        words = [{"x0": 50, "x1": 250}, {"x0": 350, "x1": 550}] * 50
        page = _StubPage(words, left="left col", right="REFERENCES\nright col", full="mixed")
        text = CirPdfTextExtractor().extract_page(page)  # type: ignore[arg-type]
        assert text == "left col\nREFERENCES\nright col"

    def test_full_width_page_is_read_as_single_column(self) -> None:
        # 가운데를 걸치는 단어가 많으면(표·제목) 컬럼으로 자르지 않는다
        words = [{"x0": 100, "x1": 500}] * 10
        page = _StubPage(words, left="l", right="r", full="whole page")
        assert CirPdfTextExtractor().extract_page(page) == "whole page"  # type: ignore[arg-type]

    def test_page_without_words_falls_back_to_full_text(self) -> None:
        page = _StubPage([], left="l", right="r", full="")
        assert CirPdfTextExtractor().extract_page(page) == ""  # type: ignore[arg-type]
