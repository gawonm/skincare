"""PubMed smoke 10 에서 확인된 선택 오류의 회귀 테스트. 네트워크 없음.

fixture 는 실제 저장된 제목·초록 발췌다(`pubmed_smoke_fixtures.py`). 성분별 사례가 이전에는 selected 로
잘못 뽑혔고, 지금은 selected 가 아니어야 한다. 특정 성분명·논문을 하드코딩한 예외는 코드에 없다.
"""

from datetime import date
from uuid import UUID, uuid4

import pytest

from data.scripts.evidence_collector_schemas import (
    AdministrationRoute,
    CollectionIngredient,
    EvidenceGrade,
    IngredientRole,
    PubmedAssessment,
    PubmedRecord,
    PubmedSelectionDisposition,
    PubmedSelectionReason,
    SkinRelevance,
    StudyDesign,
)
from data.scripts.pubmed_evidence_rules import (
    ClaimTopicClassifier,
    RouteClassifier,
    SkinRelevanceClassifier,
    StudyDesignClassifier,
)
from data.scripts.pubmed_selection_policy import PubmedSelectionPolicy
from models.evidence_document import EvidenceClaimTopic, EvidenceFormulationType, EvidenceStudyType
from tests.unit.pubmed_smoke_fixtures import FIXTURES

_SELECTED = PubmedSelectionDisposition.SELECTED
_CANDIDATE = PubmedSelectionDisposition.CANDIDATE


def _ingredient(name: str, aliases: list[str] | None = None) -> CollectionIngredient:
    return CollectionIngredient(ingredient_id=uuid4(), standard_name_en=name, aliases=aliases or [])


def _record(pmid: str, *, trial: bool | None = None) -> PubmedRecord:
    fixture = FIXTURES[pmid]
    title = fixture["title"]
    lowered = title.lower()
    if trial is None:
        trial = "randomized" in lowered or "trial" in lowered
    publication_types = ["Randomized Controlled Trial"] if trial else ["Journal Article"]
    if "systematic review" in lowered or "meta-analysis" in lowered:
        publication_types = ["Systematic Review", "Meta-Analysis"]
    return PubmedRecord(
        pmid=pmid,
        doi=None,
        title=title,
        abstract=fixture["abstract"],
        journal=None,
        publication_date=date(2024, 1, 1),
        publication_types=publication_types,
        # 저장 bundle 에 MeSH 가 없어 세포 실험에도 붙는 "Humans" 로 재구성했다
        mesh_terms=["Humans"],
        authors=[],
    )


def _assess_one(name: str, pmid: str) -> PubmedAssessment | None:
    result = PubmedSelectionPolicy(3).assess(_ingredient(name), [_record(pmid)])
    return result[0] if result else None


class TestRetinolComparatorOnly:
    def test_hexapeptide9_paper_where_retinol_is_the_comparator_is_not_direct_evidence(
        self,
    ) -> None:
        assessment = _assess_one("Retinol", "40586182")
        assert assessment is not None
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.COMPARATOR_ONLY
        assert assessment.ingredient_role is IngredientRole.COMPARATOR_OR_BACKGROUND


class TestInVitroIsNotHuman:
    @pytest.mark.parametrize("pmid", ["42353265", "37652708", "39537961"])
    def test_cell_and_proteomics_studies_are_not_classified_as_human(self, pmid: str) -> None:
        record = _record(pmid)
        design = StudyDesignClassifier().classify(record)
        assert design is StudyDesign.IN_VITRO
        assert PubmedSelectionPolicy().classify_study_type(record) is EvidenceStudyType.IN_VITRO
        assessment = _assess_one("3-O-Ethyl Ascorbic Acid", pmid)
        assert assessment is None or assessment.disposition is not _SELECTED


class TestRouteFiltering:
    @pytest.mark.parametrize(
        ("name", "pmid", "route"),
        [
            ("Collagen", "37822045", AdministrationRoute.ORAL),
            ("Collagen", "33742704", AdministrationRoute.ORAL),
            ("Sodium Hyaluronate", "41422283", AdministrationRoute.ORAL),
            ("Sodium Hyaluronate", "41117156", AdministrationRoute.INJECTION),
            ("Centella asiatica", "42196964", AdministrationRoute.ORAL),
        ],
    )
    def test_oral_and_injection_studies_are_candidates_with_reason(
        self, name: str, pmid: str, route: AdministrationRoute
    ) -> None:
        assessment = _assess_one(name, pmid)
        assert assessment is not None
        assert assessment.route is route
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.ROUTE_NOT_TOPICAL

    def test_collagen_mixed_ex_vivo_and_oral_trial_is_not_selected(self) -> None:
        assessment = _assess_one("Collagen", "26362110")
        assert assessment is None or assessment.disposition is not _SELECTED

    def test_in_vitro_design_has_no_route_and_is_never_selected(self) -> None:
        record = _record("36278820")
        design = StudyDesignClassifier().classify(record)
        assert design is StudyDesign.IN_VITRO
        assert RouteClassifier().classify(record, design) is AdministrationRoute.NOT_APPLICABLE
        assessment = _assess_one("Centella asiatica", "36278820")
        assert assessment is not None
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.NON_CLINICAL_STUDY_DESIGN

    def test_liposome_formulation_paper_is_not_selected_as_topical_evidence(self) -> None:
        assessment = _assess_one("Sodium Hyaluronate", "24724824")
        assert assessment is None or assessment.disposition is not _SELECTED


class TestSkinRelevance:
    def test_cystinosis_paper_is_dropped_because_skin_only_names_the_cell_source(self) -> None:
        record = _record("370586")
        assert SkinRelevanceClassifier().classify(record) is SkinRelevance.NOT_RELEVANT
        # 근거 후보에도 남기지 않는다(성분 이름만 걸린 비피부 논문)
        assert PubmedSelectionPolicy().assess(_ingredient("Ascorbic Acid"), [record]) == []

    def test_non_skin_toxicology_paper_is_dropped_without_special_casing_the_term(self) -> None:
        # BHA 는 모호한 raw query 의 관찰 사례일 뿐이다: 특수처리 없이 일반 규칙으로 걸러진다
        record = _record("28115641")
        assert PubmedSelectionPolicy().assess(_ingredient("BHA"), [record]) == []

    def test_topical_human_trial_still_passes_as_positive_control(self) -> None:
        assessment = _assess_one("Ascorbic Acid", "15304189")
        assert assessment is not None
        assert assessment.disposition is _SELECTED
        assert assessment.route is AdministrationRoute.TOPICAL
        assert assessment.evidence_grade is EvidenceGrade.DIRECT_SINGLE_TOPICAL_HUMAN


class TestCombinationHandling:
    def test_combination_paper_is_kept_but_ranked_after_single_ingredient_paper(self) -> None:
        policy = PubmedSelectionPolicy(1)
        combo = _record("38299457")
        single = _record("36683259")
        result = policy.assess(_ingredient("Niacinamide", ["Nicotinamide"]), [combo, single])
        by_pmid = {a.record.pmid: a for a in result}
        assert by_pmid["38299457"].formulation_type is (
            EvidenceFormulationType.COMBINATION_FORMULATION
        )
        # 복합 제형은 예산과 무관하게 복수 성분 association 검수 대상으로 남는다
        assert by_pmid["36683259"].disposition is _SELECTED
        assert by_pmid["36683259"].evidence_grade is EvidenceGrade.DIRECT_SINGLE_TOPICAL_HUMAN
        assert by_pmid["38299457"].disposition is _CANDIDATE
        assert by_pmid["38299457"].reason is (
            PubmedSelectionReason.COMBINATION_REQUIRES_ASSOCIATION_MAPPING
        )

    def test_combination_requires_reviewed_association_mapping(self) -> None:
        (assessment,) = PubmedSelectionPolicy(3).assess(
            _ingredient("Niacinamide", ["Nicotinamide"]), [_record("38299457")]
        )
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is (
            PubmedSelectionReason.COMBINATION_REQUIRES_ASSOCIATION_MAPPING
        )
        assert assessment.evidence_grade is EvidenceGrade.COMBINATION_TOPICAL_HUMAN


class TestNoForcedSelection:
    def test_no_records_means_zero_selected(self) -> None:
        # Hexapeptide-2 smoke: PubMed 결과 0건. 예산을 채우려 하지 않는다
        assert PubmedSelectionPolicy(3).assess(_ingredient("Hexapeptide-2"), []) == []

    def test_only_inappropriate_records_means_zero_selected(self) -> None:
        records = [_record(p) for p in ("37822045", "41422283", "42353265", "370586")]
        result = PubmedSelectionPolicy(3).assess(_ingredient("Collagen"), records)
        assert not [a for a in result if a.disposition is _SELECTED]


class TestClaimTopics:
    def _record(self, title: str, abstract: str) -> PubmedRecord:
        return PubmedRecord(
            pmid="1",
            doi=None,
            title=title,
            abstract=abstract,
            journal=None,
            publication_date=None,
            publication_types=[],
            mesh_terms=[],
            authors=[],
        )

    def test_topic_requires_abstract_support_not_title_only(self) -> None:
        record = self._record("Niacinamide and irritation", "Volunteers used a cream.")
        assert ClaimTopicClassifier().classify(record) == []

    def test_cytotoxic_or_generic_safety_word_does_not_create_precaution(self) -> None:
        record = self._record("X", "No cytotoxicity was observed in cells.")
        assert EvidenceClaimTopic.PRECAUTION not in ClaimTopicClassifier().classify(record)

    def test_empty_topics_are_never_auto_selected(self) -> None:
        record = PubmedRecord(
            pmid="9",
            doi=None,
            title="Niacinamide cream on facial skin",
            abstract="Volunteers applied a topical cream to facial skin in a randomized trial.",
            journal=None,
            publication_date=None,
            publication_types=["Randomized Controlled Trial"],
            mesh_terms=[],
            authors=[],
        )
        (assessment,) = PubmedSelectionPolicy(3).assess(_ingredient("Niacinamide"), [record])
        assert assessment.claim_topics == []
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.NO_CLAIM_TOPIC


class TestRouteUnclear:
    def test_unclear_route_is_not_treated_as_topical(self) -> None:
        record = PubmedRecord(
            pmid="5",
            doi=None,
            title="Niacinamide for skin wrinkles",
            abstract="Volunteers received niacinamide in a randomized trial; skin wrinkles improved.",
            journal=None,
            publication_date=None,
            publication_types=["Randomized Controlled Trial"],
            mesh_terms=[],
            authors=[],
        )
        (assessment,) = PubmedSelectionPolicy(3).assess(_ingredient("Niacinamide"), [record])
        assert assessment.route is AdministrationRoute.UNCLEAR
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.ROUTE_UNCLEAR

    def test_oral_cavity_wording_is_not_oral_administration(self) -> None:
        record = PubmedRecord(
            pmid="6",
            doi=None,
            title="Topical gel for oral mucosa lesions",
            abstract="A gel was applied to the oral cavity.",
            journal=None,
            publication_date=None,
            publication_types=["Randomized Controlled Trial"],
            mesh_terms=[],
            authors=[],
        )
        design = StudyDesignClassifier().classify(record)
        assert RouteClassifier().classify(record, design) is AdministrationRoute.TOPICAL


class TestAliasContract:
    def test_only_given_exact_aliases_are_used_and_nothing_is_added(self) -> None:
        policy = PubmedSelectionPolicy()
        plain = _ingredient("Ascorbic Acid")
        # 파생형·family 용어("vitamin C", "sodium ascorbyl phosphate")는 collector 가 임의로 덧붙이지 않는다
        assert policy.search_names(plain) == ["Ascorbic Acid"]
        with_alias = _ingredient("Niacinamide", ["Nicotinamide"])
        assert policy.search_names(with_alias) == ["Niacinamide", "Nicotinamide"]

    def test_collector_input_exports_only_old_names_as_aliases(self) -> None:
        from data.scripts.evidence_collection_universe import (
            FAMILY_RULES,
            CollectorInputExporter,
        )

        ingredient_id = UUID("00000000-0000-0000-0000-0000000000aa")
        built = CollectorInputExporter.build_ingredient(
            ingredient_id, "Ascorbic Acid", "아스코빅애씨드", ["L-Ascorbic Acid", "Ascorbic Acid"]
        )
        assert built.aliases == ["L-Ascorbic Acid"]  # 구 영문명만, 자기 자신은 제외
        # vitamin_c family 가 있어도 expansion 용어는 자동으로 들어가지 않는다
        assert any(f.name == "vitamin_c" for f in FAMILY_RULES)
        bare = CollectorInputExporter.build_ingredient(ingredient_id, "Ascorbic Acid", None, [])
        assert bare.aliases == []


def _plain(title: str, abstract: str, pubtypes: list[str] | None = None) -> PubmedRecord:
    return PubmedRecord(
        pmid="77",
        doi=None,
        title=title,
        abstract=abstract,
        journal=None,
        publication_date=None,
        publication_types=pubtypes or ["Randomized Controlled Trial"],
        mesh_terms=[],
        authors=[],
    )


class TestMixedDesignIsCandidate:
    def test_formulation_development_paper_with_clinical_pubtype_is_not_selected(self) -> None:
        # 실제 smoke 재현: publication type 이 Clinical Trial 이고 초록은 제형 개발(in vitro 단서 포함)
        record = _record("24724824", trial=True)
        record = record.model_copy(
            update={"publication_types": ["Clinical Trial", "Comparative Study"]}
        )
        (assessment,) = PubmedSelectionPolicy(3).assess(_ingredient("Sodium Hyaluronate"), [record])
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.MIXED_DESIGN_REVIEW


class TestLexicalGaps:
    def test_scar_and_skin_wound_are_skin_relevant_but_oral_wound_is_not(self) -> None:
        scar = _plain("Cream on scar development after surgery", "Patients applied a cream.")
        assert SkinRelevanceClassifier().classify(scar) is SkinRelevance.RELEVANT
        skin_wound = _plain("Spray film on acute wounds", "Wound healing was measured.")
        assert SkinRelevanceClassifier().classify(skin_wound) is SkinRelevance.RELEVANT
        palatal = _plain("Gel on palatal wound healing", "Patients rinsed. Oral wound pain fell.")
        assert SkinRelevanceClassifier().classify(palatal) is SkinRelevance.NOT_RELEVANT

    def test_seborrheic_and_scalp_are_skin_relevant(self) -> None:
        record = _plain("Wipes in infant seborrheic dermatitis", "Scalp scaling improved.")
        assert SkinRelevanceClassifier().classify(record) is SkinRelevance.RELEVANT

    @pytest.mark.parametrize("word", ["emulsion", "mask", "peel", "shampoo", "wipes"])
    def test_topical_vehicle_words_give_topical_route(self, word: str) -> None:
        record = _plain(
            f"Niacinamide {word} for facial skin", "Volunteers used it in a randomized trial."
        )
        design = StudyDesignClassifier().classify(record)
        assert RouteClassifier().classify(record, design) is AdministrationRoute.TOPICAL


class TestCombinationFalsePositive:
    @pytest.mark.parametrize("tail", ["and its effects", "and their effects", "and the skin"])
    def test_and_its_their_the_is_not_a_combination(self, tail: str) -> None:
        record = _plain(f"Use of topical ascorbic acid {tail} on photodamaged skin", "x")
        policy = PubmedSelectionPolicy()
        assert policy.classify_formulation(record, ["ascorbic acid"]) is (
            EvidenceFormulationType.SINGLE_INGREDIENT
        )

    def test_real_combination_is_still_detected(self) -> None:
        record = _plain("Ascorbic acid and glycerin for skin", "x")
        assert PubmedSelectionPolicy().classify_formulation(record, ["ascorbic acid"]) is (
            EvidenceFormulationType.COMBINATION_FORMULATION
        )


class TestEncapsulationPaper:
    def test_retinol_encapsulation_paper_with_clinical_pubtype_is_not_selected(self) -> None:
        record = _plain(
            "Encapsulation and controlled release of retinol from silicone particles for topical delivery.",
            "Retinol reduces wrinkles in facial skin. We encapsulate retinol in silicone particles prepared by sol-gel "
            "polymerization and study the release kinetics. Volunteers applied the cream in a randomized test.",
            ["Comparative Study", "Controlled Clinical Trial"],
        )
        (assessment,) = PubmedSelectionPolicy(3).assess(_ingredient("Retinol"), [record])
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.MIXED_DESIGN_REVIEW


class TestAnimalHumanPrecedence:
    """full collection 재평가에서 확인된 구조적 결함: animal 단서가 임상 단서에 가려지던 문제."""

    _CYSTEINE_TITLE = "Topical and Systemic Effects of N-acetyl Cysteine on Wound Healing in a Diabetic Rat Model."
    _CYSTEINE_ABSTRACT = (
        "OBJECTIVE: This study evaluates the effects of topical and systemic N-acetyl cysteine (NAC) treatment "
        "on wound healing in a diabetic rat model. A total of 48 male Wistar Albino rats were randomly divided "
        "into 4 groups. A full-thickness wound was created on the back of each animal and treated with NAC gauze; "
        "the wounded skin area was measured and skin histopathology assessed."
    )
    _RASPBERRY_TITLE = (
        "Effect of topical application of raspberry ketone on dermal production of insulin-like growth "
        "factor-I in mice and on hair growth and skin elasticity in humans."
    )
    _RASPBERRY_ABSTRACT = (
        "We examined this possibility in mice and humans. Raspberry ketone increased CGRP release from "
        "neurons isolated from wild-type mice. Topical application of 0.01% RK increased dermal IGF-I levels "
        "in mice, and in a placebo-controlled study it improved skin elasticity and hair growth in humans."
    )

    def _rec(self, title: str, abstract: str, pubtypes: list[str], mesh: list[str]) -> PubmedRecord:
        return PubmedRecord(
            pmid="88",
            doi=None,
            title=title,
            abstract=abstract,
            journal=None,
            publication_date=None,
            publication_types=pubtypes,
            mesh_terms=mesh,
            authors=[],
        )

    def test_rat_model_with_misattached_trial_metadata_is_animal_and_not_selected(self) -> None:
        # 실제 PubMed 레코드: 쥐 논문인데 publication type 에 RCT, MeSH 에 Humans 가 붙어 있었다
        record = self._rec(
            self._CYSTEINE_TITLE,
            self._CYSTEINE_ABSTRACT,
            ["Comparative Study", "Randomized Controlled Trial"],
            ["Humans", "Wound Healing"],
        )
        assert StudyDesignClassifier().classify(record) is StudyDesign.ANIMAL
        (assessment,) = PubmedSelectionPolicy(3).assess(_ingredient("Cysteine"), [record])
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.NON_CLINICAL_STUDY_DESIGN

    def test_mice_plus_humans_is_mixed_and_not_selected(self) -> None:
        record = self._rec(
            self._RASPBERRY_TITLE,
            self._RASPBERRY_ABSTRACT,
            ["Clinical Trial", "Randomized Controlled Trial"],
            ["Animals", "Humans"],
        )
        assert StudyDesignClassifier().classify(record) is StudyDesign.MIXED_HUMAN_AND_LAB
        (assessment,) = PubmedSelectionPolicy(3).assess(_ingredient("Raspberry Ketone"), [record])
        assert assessment.disposition is _CANDIDATE
        assert assessment.reason is PubmedSelectionReason.MIXED_DESIGN_REVIEW

    def test_human_only_trial_still_human_clinical(self) -> None:
        record = self._rec(
            "Topical niacinamide cream for facial skin wrinkles",
            "Forty volunteers applied a topical cream to facial skin in a randomized trial; wrinkles improved.",
            ["Randomized Controlled Trial"],
            ["Humans"],
        )
        assert StudyDesignClassifier().classify(record) is StudyDesign.HUMAN_CLINICAL

    def test_animal_only_without_trial_metadata_is_animal(self) -> None:
        record = self._rec("Effects on mouse skin", "Mice were treated topically.", [], ["Animals"])
        assert StudyDesignClassifier().classify(record) is StudyDesign.ANIMAL

    def test_stray_animals_mesh_on_human_trial_does_not_make_it_animal(self) -> None:
        record = self._rec(
            "Effectiveness of a zinc oxide cream for mosquito bite symptoms",
            "Participants applied a topical cream in a controlled clinical trial; subjects reported less itching.",
            ["Controlled Clinical Trial"],
            ["Animals", "Humans"],
        )
        assert StudyDesignClassifier().classify(record) is StudyDesign.HUMAN_CLINICAL

    def test_canine_study_is_animal(self) -> None:
        record = self._rec(
            "Topical emulsion for canine atopic dermatitis",
            "A randomized, double-blind study in dogs with atopic dermatitis.",
            ["Randomized Controlled Trial"],
            ["Humans"],
        )
        assert StudyDesignClassifier().classify(record) is StudyDesign.ANIMAL
