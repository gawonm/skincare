"""PubMed collector 단위 테스트. 네트워크 없이 XML fixture 와 fake source 만 쓴다."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from data.scripts.compact_evidence_collector import CompactEvidenceCollectorRunner
from data.scripts.evidence_collector_schemas import (
    CollectionIngredient,
    PubmedRecord,
    PubmedSelectionDisposition,
    PubmedSelectionReason,
)
from data.scripts.pubmed_evidence_collector import PubmedEvidenceCollector
from data.scripts.pubmed_evidence_mapper import PubmedEvidenceMapper
from data.scripts.pubmed_selection_policy import (
    MAX_PAPERS_HARD_LIMIT,
    PubmedSelectionPolicy,
)
from data.scripts.pubmed_xml_parser import PubmedXmlParser
from models.evidence_document import (
    EvidenceClaimTopic,
    EvidenceDocumentSourceType,
    EvidenceFormulationType,
    EvidenceLevel,
    EvidenceStudyType,
)

_NOW = datetime(2026, 9, 21, tzinfo=UTC)
_NIACINAMIDE = CollectionIngredient(
    ingredient_id=UUID("00000000-0000-0000-0000-000000000001"),
    standard_name_en="Niacinamide",
    standard_name_ko="나이아신아마이드",
    aliases=["Nicotinamide", "나이아신아마이드"],
)


def _article_xml(
    pmid: str = "111",
    *,
    title: str = "Niacinamide reduces wrinkles",
    abstract_parts: list[tuple[str | None, str]] | None = None,
    doi: str | None = "10.1/x",
    pub_types: tuple[str, ...] = ("Randomized Controlled Trial",),
    mesh: tuple[str, ...] = ("Humans", "Niacinamide"),
    year: str = "2020",
    month: str = "Mar",
) -> str:
    parts = (
        [(None, "Twenty subjects used niacinamide.")] if abstract_parts is None else abstract_parts
    )
    abstract = ""
    if parts:
        texts = "".join(
            f"<AbstractText{f' Label={chr(34)}{label}{chr(34)}' if label else ''}>{text}</AbstractText>"
            for label, text in parts
        )
        abstract = f"<Abstract>{texts}</Abstract>"
    doi_xml = f'<ArticleId IdType="doi">{doi}</ArticleId>' if doi else ""
    return f"""<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
<Journal><JournalIssue><PubDate><Year>{year}</Year><Month>{month}</Month></PubDate></JournalIssue>
<Title>J Cosmet Dermatol</Title></Journal>
<ArticleTitle>{title}</ArticleTitle>{abstract}
<AuthorList><Author><LastName>Kim</LastName><Initials>J</Initials></Author></AuthorList>
<PublicationTypeList>{"".join(f"<PublicationType>{t}</PublicationType>" for t in pub_types)}</PublicationTypeList>
</Article><MeshHeadingList>{"".join(f"<MeshHeading><DescriptorName>{m}</DescriptorName></MeshHeading>" for m in mesh)}</MeshHeadingList>
</MedlineCitation><PubmedData><ArticleIdList>{doi_xml}</ArticleIdList></PubmedData></PubmedArticle>"""


def _xml(*articles: str) -> str:
    return f"<PubmedArticleSet>{''.join(articles)}</PubmedArticleSet>"


def _record(pmid: str = "1", **overrides: object) -> PubmedRecord:
    (parsed,) = PubmedXmlParser().parse(_xml(_article_xml(pmid)))
    return parsed.model_copy(update=overrides)


class TestParser:
    def test_parses_all_metadata(self) -> None:
        (record,) = PubmedXmlParser().parse(_xml(_article_xml("42")))
        assert record.pmid == "42"
        assert record.doi == "10.1/x"
        assert record.journal == "J Cosmet Dermatol"
        assert record.publication_date == date(2020, 3, 1)
        assert record.publication_types == ["Randomized Controlled Trial"]
        assert record.mesh_terms == ["Humans", "Niacinamide"]
        assert record.authors == ["Kim J"]
        assert record.url == "https://pubmed.ncbi.nlm.nih.gov/42/"

    def test_missing_doi_is_none(self) -> None:
        (record,) = PubmedXmlParser().parse(_xml(_article_xml(doi=None)))
        assert record.doi is None

    def test_missing_abstract_is_none(self) -> None:
        (record,) = PubmedXmlParser().parse(_xml(_article_xml(abstract_parts=[])))
        assert record.abstract is None

    def test_structured_abstract_keeps_labels_verbatim(self) -> None:
        parts = [("BACKGROUND", "Skin barrier."), ("RESULTS", "Improved.")]
        (record,) = PubmedXmlParser().parse(_xml(_article_xml(abstract_parts=parts)))
        assert record.abstract == "BACKGROUND: Skin barrier.\nRESULTS: Improved."

    def test_invalid_xml_raises_with_message(self) -> None:
        with pytest.raises(RuntimeError, match="파싱 실패"):
            PubmedXmlParser().parse("<broken")


class TestSelectionPolicy:
    def test_budget_hard_limit_is_enforced(self) -> None:
        with pytest.raises(ValueError, match="1~4"):
            PubmedSelectionPolicy(MAX_PAPERS_HARD_LIMIT + 1)
        with pytest.raises(ValueError):
            PubmedSelectionPolicy(0)

    def test_queries_exclude_non_ascii_names(self) -> None:
        policy = PubmedSelectionPolicy()
        assert policy.search_names(_NIACINAMIDE) == ["Niacinamide", "Nicotinamide"]
        query = policy.build_clinical_query(_NIACINAMIDE)
        assert '"Niacinamide"[Title/Abstract] OR "Nicotinamide"[Title/Abstract]' in query
        assert "나이아신" not in query

    def test_no_english_name_raises(self) -> None:
        ingredient = CollectionIngredient(
            ingredient_id=uuid4(), standard_name_en="나이아신아마이드"
        )
        with pytest.raises(ValueError, match="영문 검색어"):
            PubmedSelectionPolicy().search_names(ingredient)

    def test_selects_at_most_budget_and_rest_become_candidates(self) -> None:
        policy = PubmedSelectionPolicy(max_papers_per_ingredient=2)
        records = [_record(str(pmid)) for pmid in range(1, 6)]
        result = policy.assess(_NIACINAMIDE, records)
        selected = [a for a in result if a.disposition is PubmedSelectionDisposition.SELECTED]
        over_budget = [a for a in result if a.reason is PubmedSelectionReason.OVER_BUDGET]
        assert len(selected) == 2
        assert len(over_budget) == 3

    def test_pmid_dedup(self) -> None:
        result = PubmedSelectionPolicy().assess(_NIACINAMIDE, [_record("7"), _record("7")])
        assert [a.record.pmid for a in result] == ["7"]

    def test_record_without_abstract_is_rejected_not_returned(self) -> None:
        result = PubmedSelectionPolicy().assess(_NIACINAMIDE, [_record("1", abstract=None)])
        assert result == []

    def test_excluded_publication_type_is_dropped(self) -> None:
        record = _record("1", publication_types=["Editorial"])
        assert PubmedSelectionPolicy().assess(_NIACINAMIDE, [record]) == []

    def test_unrelated_paper_is_dropped(self) -> None:
        record = _record(
            "1", title="Retinol study", abstract="Retinol only.", mesh_terms=["Humans"]
        )
        assert PubmedSelectionPolicy().assess(_NIACINAMIDE, [record]) == []

    def test_ingredient_only_in_abstract_stays_candidate(self) -> None:
        record = _record("1", title="A skin study", abstract="They applied niacinamide.")
        (assessment,) = PubmedSelectionPolicy().assess(_NIACINAMIDE, [record])
        assert assessment.disposition is PubmedSelectionDisposition.CANDIDATE
        assert assessment.reason is PubmedSelectionReason.INGREDIENT_NOT_IN_TITLE

    def test_in_vitro_and_unknown_study_types_are_candidates_not_selected(self) -> None:
        in_vitro = _record(
            "1", publication_types=["Journal Article"], mesh_terms=["In Vitro Techniques"]
        )
        unknown = _record("2", publication_types=["Journal Article"], mesh_terms=["Niacinamide"])
        result = PubmedSelectionPolicy().assess(_NIACINAMIDE, [in_vitro, unknown])
        assert {a.disposition for a in result} == {PubmedSelectionDisposition.CANDIDATE}
        assert {a.study_type for a in result} == {
            EvidenceStudyType.IN_VITRO,
            EvidenceStudyType.UNKNOWN,
        }

    def test_publication_type_classification(self) -> None:
        policy = PubmedSelectionPolicy()
        trial = _record(publication_types=["Randomized Controlled Trial"], mesh_terms=[])
        review = _record(publication_types=["Systematic Review"], mesh_terms=["Humans"])
        mixed = _record(
            publication_types=["Journal Article"], mesh_terms=["Humans", "In Vitro Techniques"]
        )
        animal = _record(publication_types=["Journal Article"], mesh_terms=["Animals"])
        assert policy.classify_study_type(trial) is EvidenceStudyType.HUMAN_STUDY
        assert policy.classify_study_type(review) is EvidenceStudyType.REVIEW
        assert policy.classify_study_type(mixed) is EvidenceStudyType.MIXED_IN_VITRO_AND_HUMAN
        assert policy.classify_study_type(animal) is EvidenceStudyType.ANIMAL_STUDY

    def test_combination_formulation_is_flagged_and_ranked_lower(self) -> None:
        policy = PubmedSelectionPolicy()
        names = policy.search_names(_NIACINAMIDE)
        combo = _record("1", title="Niacinamide and glycerin products reduce roughness")
        single = _record("2", title="Niacinamide reduces roughness")
        plain_with = _record("3", title="Niacinamide in patients with acne")
        assert (
            policy.classify_formulation(combo, names)
            is EvidenceFormulationType.COMBINATION_FORMULATION
        )
        assert (
            policy.classify_formulation(single, names) is EvidenceFormulationType.SINGLE_INGREDIENT
        )
        assert (
            policy.classify_formulation(plain_with, names)
            is EvidenceFormulationType.SINGLE_INGREDIENT
        )
        result = policy.assess(_NIACINAMIDE, [combo, single])
        assert result[0].record.pmid == "2"

    def test_claim_topics_from_text(self) -> None:
        record = _record(
            "1",
            title="Niacinamide wrinkles and irritation",
            abstract="Mild irritation, fewer wrinkle.",
        )
        (assessment,) = PubmedSelectionPolicy().assess(_NIACINAMIDE, [record])
        assert assessment.claim_topics == [
            EvidenceClaimTopic.EFFICACY,
            EvidenceClaimTopic.PRECAUTION,
        ]


class _FakeSource:
    """네트워크 대체. query 순서대로 준비된 PMID 를 돌려주고 호출을 기록한다."""

    def __init__(self, search_results: list[list[str]], records: dict[str, PubmedRecord]) -> None:
        self._search_results = search_results
        self._records = records
        self.search_calls: list[tuple[str, int]] = []
        self.fetch_calls: list[list[str]] = []
        self.request_count = 0

    def search(self, query: str, retmax: int) -> list[str]:
        self.search_calls.append((query, retmax))
        return self._search_results[len(self.search_calls) - 1]

    def fetch(self, pmids: list[str]) -> list[PubmedRecord]:
        self.fetch_calls.append(pmids)
        return [self._records[p] for p in pmids if p in self._records]


class TestCollector:
    def test_stops_after_first_query_when_budget_filled(self) -> None:
        records = {str(i): _record(str(i)) for i in range(1, 5)}
        source = _FakeSource([["1", "2", "3", "4"]], records)
        result = PubmedEvidenceCollector(source, PubmedSelectionPolicy(4)).collect(_NIACINAMIDE)
        assert len(source.search_calls) == 1
        assert len(result.selected) == 4

    def test_second_query_only_fetches_new_pmids_and_dedups(self) -> None:
        records = {str(i): _record(str(i)) for i in range(1, 4)}
        source = _FakeSource([["1", "2"], ["2", "3"]], records)
        result = PubmedEvidenceCollector(source, PubmedSelectionPolicy(4)).collect(_NIACINAMIDE)
        assert source.fetch_calls == [["1", "2"], ["3"]]
        assert sorted(a.record.pmid for a in result.selected) == ["1", "2", "3"]
        assert result.queries_run == 2

    def test_search_is_bounded(self) -> None:
        source = _FakeSource([[], []], {})
        PubmedEvidenceCollector(source, PubmedSelectionPolicy()).collect(_NIACINAMIDE)
        assert all(retmax <= 15 for _, retmax in source.search_calls)


class TestMapper:
    def test_one_abstract_is_one_chunk_with_provenance(self) -> None:
        policy = PubmedSelectionPolicy()
        (assessment,) = policy.assess(_NIACINAMIDE, [_record("16766489")])
        bundle = PubmedEvidenceMapper().to_bundle(
            assessment,
            ingredient_ids=[_NIACINAMIDE.ingredient_id],
            raw_ingredient_names=["Niacinamide"],
            retrieved_at=_NOW,
        )
        (chunk,) = bundle.chunks
        document = bundle.document
        assert document.source_id == "PMID:16766489"
        assert document.source_type is EvidenceDocumentSourceType.PUBMED_ABSTRACT
        assert document.evidence_level is EvidenceLevel.PEER_REVIEWED_STUDY
        assert document.pmid == "16766489" and document.doi == "10.1/x"
        assert document.url == "https://pubmed.ncbi.nlm.nih.gov/16766489/"
        assert chunk.chunk_id == "PMID:16766489:abstract:0"
        assert (chunk.section, chunk.chunk_index, chunk.page) == ("abstract", 0, None)
        assert chunk.content == assessment.record.abstract
        assert len(chunk.content_hash) == 64
        assert chunk.pmid == "16766489" and chunk.url == document.url

    def test_missing_doi_is_kept_as_none(self) -> None:
        (assessment,) = PubmedSelectionPolicy().assess(_NIACINAMIDE, [_record("1", doi=None)])
        bundle = PubmedEvidenceMapper().to_bundle(
            assessment, ingredient_ids=[], raw_ingredient_names=[], retrieved_at=_NOW
        )
        assert bundle.document.doi is None and bundle.chunks[0].doi is None

    def test_record_without_abstract_cannot_be_mapped(self) -> None:
        (assessment,) = PubmedSelectionPolicy().assess(_NIACINAMIDE, [_record("1")])
        empty = assessment.model_copy(
            update={"record": assessment.record.model_copy(update={"abstract": None})}
        )
        with pytest.raises(ValueError, match="abstract"):
            PubmedEvidenceMapper().to_bundle(
                empty, ingredient_ids=[], raw_ingredient_names=[], retrieved_at=_NOW
            )


class TestRunner:
    def _runner(
        self, tmp_path: Path, source: _FakeSource, *, dry_run: bool = False
    ) -> CompactEvidenceCollectorRunner:
        return CompactEvidenceCollectorRunner(
            output_path=tmp_path / "bundles.jsonl",
            candidates_path=tmp_path / "candidates.jsonl",
            dry_run=dry_run,
            pubmed_source=source,
            now=_NOW,
        )

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        source = _FakeSource([["1"], ["1"]], {"1": _record("1")})
        summary = self._runner(tmp_path, source, dry_run=True).run_pubmed([_NIACINAMIDE])
        assert summary.documents_selected == 1
        assert not (tmp_path / "bundles.jsonl").exists()

    def test_rerun_does_not_duplicate_or_refetch(self, tmp_path: Path) -> None:
        source = _FakeSource([["1", "2"], ["1", "2"]], {"1": _record("1"), "2": _record("2")})
        first = self._runner(tmp_path, source).run_pubmed([_NIACINAMIDE])
        second_source = _FakeSource([], {})
        second = self._runner(tmp_path, second_source).run_pubmed([_NIACINAMIDE])
        lines = (tmp_path / "bundles.jsonl").read_text(encoding="utf-8").splitlines()
        assert first.documents_new == 2 and len(lines) == 2
        assert second.ingredients_skipped_already_collected == 1
        assert second_source.search_calls == []

    def test_same_pmid_for_two_ingredients_merges_links(self, tmp_path: Path) -> None:
        other = CollectionIngredient(ingredient_id=uuid4(), standard_name_en="Niacinamide")
        source = _FakeSource([["1"], ["1"], ["1"], ["1"]], {"1": _record("1")})
        runner = self._runner(tmp_path, source)
        summary = runner.run_pubmed([_NIACINAMIDE, other])
        (line,) = (tmp_path / "bundles.jsonl").read_text(encoding="utf-8").splitlines()
        assert summary.documents_new == 1
        assert set(map(UUID, json.loads(line)["document"]["ingredient_ids"])) == {
            _NIACINAMIDE.ingredient_id,
            other.ingredient_id,
        }


class TestCosmeticContextRanking:
    def test_topical_paper_outranks_oral_supplement_paper(self) -> None:
        oral = _record(
            "1",
            title="Niacinamide supplementation in patients",
            abstract="Oral tablets were given.",
        )
        topical = _record(
            "2", title="Niacinamide in patients", abstract="A topical cream was applied."
        )
        result = PubmedSelectionPolicy().assess(_NIACINAMIDE, [oral, topical])
        assert [a.record.pmid for a in result][:2] == ["2", "1"]
