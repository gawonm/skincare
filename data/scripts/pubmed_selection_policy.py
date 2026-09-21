"""PubMed 후보 record 를 성분 기준으로 평가·선별하는 정책. 네트워크·LLM 없음.

title / abstract / publication type / MeSH 만으로 결정적(deterministic)으로 판단한다.
확신할 수 없는 record 는 SELECTED 가 아니라 CANDIDATE 로 남겨 사람이 검토하게 한다.
"""

import re

from data.scripts.evidence_collector_schemas import (
    CollectionIngredient,
    PubmedAssessment,
    PubmedRecord,
    PubmedSelectionDisposition,
    PubmedSelectionReason,
)
from models.evidence_document import (
    EvidenceClaimTopic,
    EvidenceFormulationType,
    EvidenceStudyType,
)

# 성분 전체 기준 상한. "수백 편 적재" 같은 실수를 구조적으로 막으려고 생성자에서 강제한다.
MAX_PAPERS_HARD_LIMIT = 4
DEFAULT_MAX_PAPERS_PER_INGREDIENT = 4
MAX_QUERY_NAME_VARIANTS = 3

# 사람 검토용 candidate 도 무제한으로 쌓지 않는다
MAX_REVIEW_CANDIDATES_PER_INGREDIENT = 10

_TITLE_MENTION_SCORE = 3
_ABSTRACT_MENTION_SCORE = 1
_MESH_MENTION_SCORE = 1
_CLAIM_TOPIC_HIT_SCORE = 1
_COMBINATION_PENALTY = 1
_COSMETIC_CONTEXT_SCORE = 2
_MIN_SELECT_SCORE = 5

_SKIN_SCOPE_TERMS = "skin OR topical OR cosmetic OR dermatolog*"

_EXCLUDED_PUBLICATION_TYPES = frozenset(
    {
        "retracted publication",
        "retraction of publication",
        "published erratum",
        "erratum",
        "comment",
        "editorial",
        "letter",
        "news",
        "case reports",
    }
)
_TRIAL_PUBLICATION_TYPES = frozenset(
    {
        "randomized controlled trial",
        "clinical trial",
        "controlled clinical trial",
        "clinical trial, phase i",
        "clinical trial, phase ii",
        "clinical trial, phase iii",
        "clinical trial, phase iv",
        "pragmatic clinical trial",
        "equivalence trial",
    }
)
_SYSTEMATIC_PUBLICATION_TYPES = frozenset({"systematic review", "meta-analysis"})
_REVIEW_PUBLICATION_TYPE = "review"
_ANIMAL_MESH = "animals"
_HUMAN_MESH = "humans"
_IN_VITRO_MESH = "in vitro techniques"
_IN_VITRO_TITLE_PATTERN = re.compile(r"\bin vitro\b", re.IGNORECASE)

_STUDY_TYPE_SCORE = {
    EvidenceStudyType.HUMAN_STUDY: 3,
    EvidenceStudyType.REVIEW: 1,
    EvidenceStudyType.MIXED_IN_VITRO_AND_HUMAN: 1,
    EvidenceStudyType.IN_VITRO: 0,
    EvidenceStudyType.ANIMAL_STUDY: 0,
    EvidenceStudyType.UNKNOWN: 0,
}
_TRIAL_BONUS = 2
_SYSTEMATIC_REVIEW_BONUS = 3
_SELECTABLE_STUDY_TYPES = frozenset(
    {
        EvidenceStudyType.HUMAN_STUDY,
        EvidenceStudyType.REVIEW,
        EvidenceStudyType.MIXED_IN_VITRO_AND_HUMAN,
    }
)

# 서비스 대상은 화장품이라 국소 도포 맥락의 근거를 경구 복용·주사 연구보다 우선한다
_COSMETIC_CONTEXT_KEYWORDS = (
    "topical",
    "cosmetic",
    "cream",
    "moisturi",
    "lotion",
    "serum",
    "facial",
)

_CLAIM_TOPIC_KEYWORDS: dict[EvidenceClaimTopic, tuple[str, ...]] = {
    EvidenceClaimTopic.EFFICACY: (
        "wrinkle",
        "hyperpigment",
        "melasma",
        "barrier",
        "sebum",
        "acne",
        "moistur",
        "hydrat",
        "elasticity",
        "brighten",
        "pigmentation",
        "anti-aging",
        "photoaging",
    ),
    EvidenceClaimTopic.PRECAUTION: (
        "irritat",
        "sensitiz",
        "sensitis",
        "adverse",
        "allerg",
        "dermatitis",
        "safety",
        "tolerab",
        "toxic",
    ),
}
# 복합 제형 표지. 결정적 규칙이라 놓치는 경우가 있어 제외가 아니라 감점과 표시만 한다.
# "patients with acne" 같은 일반 문장의 with/and 를 오탐하지 않도록 성분명에 붙은 접속만 본다.
_COMBINATION_CONNECTOR = r"(?:,|\band\b|\bplus\b|\bwith\b|\+|/)"
_COMBINATION_KEYWORD_PATTERN = re.compile(r"\bcombination\b|\bcombined\b", re.IGNORECASE)
_NON_ASCII_LETTER_PATTERN = re.compile(r"[^\x00-\x7f]")


class PubmedSelectionPolicy:
    def __init__(self, max_papers_per_ingredient: int = DEFAULT_MAX_PAPERS_PER_INGREDIENT) -> None:
        if not 1 <= max_papers_per_ingredient <= MAX_PAPERS_HARD_LIMIT:
            raise ValueError(
                f"max_papers_per_ingredient 는 1~{MAX_PAPERS_HARD_LIMIT} 이어야 합니다"
                f"(받은 값: {max_papers_per_ingredient}). compact corpus 는 성분당 소수만 수집합니다."
            )
        self.max_papers_per_ingredient = max_papers_per_ingredient

    # ------------------------------------------------------------------ queries

    def build_clinical_query(self, ingredient: CollectionIngredient) -> str:
        return (
            f"({self._name_clause(ingredient)}) AND "
            "(randomized controlled trial[pt] OR clinical trial[pt] OR "
            "systematic review[pt] OR meta-analysis[pt]) AND "
            f"({_SKIN_SCOPE_TERMS})"
        )

    def build_human_query(self, ingredient: CollectionIngredient) -> str:
        return f"({self._name_clause(ingredient)}) AND humans[MeSH Terms] AND ({_SKIN_SCOPE_TERMS})"

    def search_names(self, ingredient: CollectionIngredient) -> list[str]:
        """PubMed 는 영문 색인이라 한글 등 비ASCII 표기는 제외한다."""
        names: list[str] = []
        for name in [ingredient.standard_name_en, *ingredient.aliases]:
            cleaned = name.replace('"', "").strip()
            if cleaned and not _NON_ASCII_LETTER_PATTERN.search(cleaned) and cleaned not in names:
                names.append(cleaned)
        if not names:
            raise ValueError(f"영문 검색어가 없는 성분입니다: {ingredient.ingredient_id}")
        return names[:MAX_QUERY_NAME_VARIANTS]

    def _name_clause(self, ingredient: CollectionIngredient) -> str:
        return " OR ".join(f'"{name}"[Title/Abstract]' for name in self.search_names(ingredient))

    # --------------------------------------------------------------- assessment

    def assess(
        self, ingredient: CollectionIngredient, records: list[PubmedRecord]
    ) -> list[PubmedAssessment]:
        """PMID 를 dedup 하고 평가한 뒤 예산 안에서 SELECTED 를 정한다.

        반환 순서는 SELECTED → CANDIDATE(상한 있음) 순이며, REJECTED 는 포함하지 않는다.
        """
        seen: set[str] = set()
        unique_records: list[PubmedRecord] = []
        for record in records:
            if record.pmid not in seen:
                seen.add(record.pmid)
                unique_records.append(record)

        assessments = [self._assess_one(ingredient, record) for record in unique_records]
        eligible = sorted(
            (a for a in assessments if a.disposition is PubmedSelectionDisposition.SELECTED),
            key=self._rank_key,
        )
        selected = eligible[: self.max_papers_per_ingredient]
        over_budget = [
            a.model_copy(
                update={
                    "disposition": PubmedSelectionDisposition.CANDIDATE,
                    "reason": PubmedSelectionReason.OVER_BUDGET,
                }
            )
            for a in eligible[self.max_papers_per_ingredient :]
        ]
        candidates = sorted(
            [
                *over_budget,
                *(a for a in assessments if a.disposition is PubmedSelectionDisposition.CANDIDATE),
            ],
            key=self._rank_key,
        )[:MAX_REVIEW_CANDIDATES_PER_INGREDIENT]
        return [*selected, *candidates]

    def _rank_key(self, assessment: PubmedAssessment) -> tuple[int, int, int]:
        year = assessment.record.publication_date.year if assessment.record.publication_date else 0
        # 점수 높은 순 → 최신 순 → PMID 오름차순(재실행 시 순서가 흔들리지 않게)
        return (-assessment.score, -year, int(assessment.record.pmid))

    def _assess_one(
        self, ingredient: CollectionIngredient, record: PubmedRecord
    ) -> PubmedAssessment:
        names = self.search_names(ingredient)
        study_type = self.classify_study_type(record)
        formulation = self.classify_formulation(record, names)
        topics = self._claim_topics(record)
        title_mentioned = self._mentions(names, record.title)
        score = self._score(record, names, study_type, formulation, topics, title_mentioned)

        disposition, reason = self._decide(record, names, study_type, title_mentioned, score)
        return PubmedAssessment(
            ingredient_id=ingredient.ingredient_id,
            record=record,
            study_type=study_type,
            formulation_type=formulation,
            claim_topics=topics,
            score=score,
            disposition=disposition,
            reason=reason,
        )

    def _decide(
        self,
        record: PubmedRecord,
        names: list[str],
        study_type: EvidenceStudyType,
        title_mentioned: bool,
        score: int,
    ) -> tuple[PubmedSelectionDisposition, PubmedSelectionReason | None]:
        rejected = PubmedSelectionDisposition.REJECTED
        candidate = PubmedSelectionDisposition.CANDIDATE
        publication_types = {value.lower() for value in record.publication_types}
        if not record.abstract:
            return rejected, PubmedSelectionReason.NO_ABSTRACT
        if publication_types & _EXCLUDED_PUBLICATION_TYPES:
            return rejected, PubmedSelectionReason.EXCLUDED_PUBLICATION_TYPE
        if not self._mentions(names, record.title, record.abstract, *record.mesh_terms):
            return rejected, PubmedSelectionReason.NOT_RELEVANT_TO_INGREDIENT
        if not title_mentioned:
            return candidate, PubmedSelectionReason.INGREDIENT_NOT_IN_TITLE
        if study_type not in _SELECTABLE_STUDY_TYPES or score < _MIN_SELECT_SCORE:
            return candidate, PubmedSelectionReason.STUDY_TYPE_NOT_SELECTABLE
        return PubmedSelectionDisposition.SELECTED, None

    def _score(
        self,
        record: PubmedRecord,
        names: list[str],
        study_type: EvidenceStudyType,
        formulation: EvidenceFormulationType,
        topics: list[EvidenceClaimTopic],
        title_mentioned: bool,
    ) -> int:
        publication_types = {value.lower() for value in record.publication_types}
        score = _STUDY_TYPE_SCORE[study_type]
        if title_mentioned:
            score += _TITLE_MENTION_SCORE
        if self._mentions(names, record.abstract or ""):
            score += _ABSTRACT_MENTION_SCORE
        if self._mentions(names, *record.mesh_terms):
            score += _MESH_MENTION_SCORE
        if publication_types & _TRIAL_PUBLICATION_TYPES:
            score += _TRIAL_BONUS
        if publication_types & _SYSTEMATIC_PUBLICATION_TYPES:
            score += _SYSTEMATIC_REVIEW_BONUS
        score += _CLAIM_TOPIC_HIT_SCORE * len(topics)
        text = f"{record.title} {record.abstract or ''}".lower()
        if any(keyword in text for keyword in _COSMETIC_CONTEXT_KEYWORDS):
            score += _COSMETIC_CONTEXT_SCORE
        if formulation is EvidenceFormulationType.COMBINATION_FORMULATION:
            score -= _COMBINATION_PENALTY
        return score

    # ----------------------------------------------------------- classification

    def classify_study_type(self, record: PubmedRecord) -> EvidenceStudyType:
        publication_types = {value.lower() for value in record.publication_types}
        mesh = {value.lower() for value in record.mesh_terms}
        is_human = _HUMAN_MESH in mesh or bool(publication_types & _TRIAL_PUBLICATION_TYPES)
        is_animal = _ANIMAL_MESH in mesh
        is_in_vitro = _IN_VITRO_MESH in mesh or bool(_IN_VITRO_TITLE_PATTERN.search(record.title))

        if (
            publication_types & _SYSTEMATIC_PUBLICATION_TYPES
            or _REVIEW_PUBLICATION_TYPE in publication_types
        ):
            return EvidenceStudyType.REVIEW
        if is_human and is_in_vitro:
            return EvidenceStudyType.MIXED_IN_VITRO_AND_HUMAN
        if is_human:
            return EvidenceStudyType.HUMAN_STUDY
        if is_animal:
            return EvidenceStudyType.ANIMAL_STUDY
        if is_in_vitro:
            return EvidenceStudyType.IN_VITRO
        return EvidenceStudyType.UNKNOWN

    def classify_formulation(
        self, record: PubmedRecord, names: list[str]
    ) -> EvidenceFormulationType:
        # ponytail: 제목에서 성분명에 붙은 접속어/기호만 본다. abstract 문맥까지 보는
        # 판정이 필요해지면 그때 규칙을 넓힌다(놓치면 단일로 표시됨).
        title = record.title
        if not self._mentions(names, title):
            return EvidenceFormulationType.SINGLE_INGREDIENT
        if _COMBINATION_KEYWORD_PATTERN.search(title):
            return EvidenceFormulationType.COMBINATION_FORMULATION
        for name in names:
            escaped = re.escape(name)
            pattern = (
                rf"{escaped}\s*{_COMBINATION_CONNECTOR}\s*[A-Za-z]"
                rf"|[A-Za-z]\s*{_COMBINATION_CONNECTOR}\s*{escaped}"
            )
            if re.search(pattern, title, re.IGNORECASE):
                return EvidenceFormulationType.COMBINATION_FORMULATION
        return EvidenceFormulationType.SINGLE_INGREDIENT

    def _claim_topics(self, record: PubmedRecord) -> list[EvidenceClaimTopic]:
        text = f"{record.title} {record.abstract or ''}".lower()
        return [
            topic
            for topic, keywords in _CLAIM_TOPIC_KEYWORDS.items()
            if any(keyword in text for keyword in keywords)
        ]

    def _mentions(self, names: list[str], *texts: str) -> bool:
        haystack = " ".join(texts)
        return any(
            re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", haystack, re.IGNORECASE)
            for name in names
        )
