"""PubMed 후보 record 를 성분 기준으로 평가·선별하는 정책. 네트워크·LLM 없음.

title / abstract / publication type / MeSH 만으로 결정적(deterministic)으로 판단한다.
SELECTED 는 "이 성분의 국소 피부 직접 근거"만이다: 피부 관련성, 임상 설계, 국소 투여, 성분이 시험 대상,
abstract 가 지지하는 claim topic 이 모두 확인돼야 한다. 확신할 수 없으면 SELECTED 가 아니라 이유를 붙인
CANDIDATE 로 남기고, 성분과 무관하거나 피부와 무관하면 버린다. 예산을 채우려고 부적절한 논문을 고르지 않으며
0편도 허용한다.
"""

import re

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
    DirectnessClassifier,
    RouteClassifier,
    SkinRelevanceClassifier,
    StudyDesignClassifier,
)
from models.evidence_document import (
    EvidenceClaimTopic,
    EvidenceFormulationType,
    EvidenceStudyType,
)

# 성분 전체 기준 상한. "수백 편 적재" 같은 실수를 구조적으로 막으려고 생성자에서 강제한다.
# 대표 근거 1~3편이 목표이고 quota 가 아니다(적합한 논문이 없으면 0편).
MAX_PAPERS_HARD_LIMIT = 3
DEFAULT_MAX_PAPERS_PER_INGREDIENT = 3
MAX_QUERY_NAME_VARIANTS = 3

# 사람 검토용 candidate 도 무제한으로 쌓지 않는다
MAX_REVIEW_CANDIDATES_PER_INGREDIENT = 10

_TITLE_MENTION_SCORE = 3
_ABSTRACT_MENTION_SCORE = 1
_MESH_MENTION_SCORE = 1
_CLAIM_TOPIC_HIT_SCORE = 1
_COMBINATION_PENALTY = 1
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
# 임상 설계로 볼 수 있는 것만 selected 후보가 된다. in vitro/ex vivo/동물/불명은 candidate 로만 남는다.
# mixed(임상+실험실)는 제형 개발 논문이 섞여 들어오므로 기본 candidate 로 둔다(예외 규칙은 만들지 않는다).
_SELECTABLE_DESIGNS = frozenset({StudyDesign.HUMAN_CLINICAL, StudyDesign.REVIEW})

# 선택 순서: 단일 성분 직접 근거 → 리뷰 → 복합 제형. 복합 제형은 제외하지 않되 뒤로 민다.
_GRADE_ORDER = {
    EvidenceGrade.DIRECT_SINGLE_TOPICAL_HUMAN: 0,
    EvidenceGrade.TOPICAL_REVIEW: 1,
    EvidenceGrade.COMBINATION_TOPICAL_HUMAN: 2,
    EvidenceGrade.NOT_GRADED: 3,
}

# 복합 제형 표지. 결정적 규칙이라 놓치는 경우가 있어 제외가 아니라 감점과 표시만 한다.
# "patients with acne" 같은 일반 문장의 with/and 를 오탐하지 않도록 성분명에 붙은 접속만 본다.
# "X and its effects" 의 and 는 다른 성분을 잇는 접속이 아니므로 its/their/the 앞은 제외한다
_COMBINATION_CONNECTOR = r"(?:,|\band\b(?!\s+(?:its|their|the)\b)|\bplus\b|\bwith\b|\+|/)"
_COMBINATION_KEYWORD_PATTERN = re.compile(r"\bcombination\b|\bcombined\b", re.IGNORECASE)
_NON_INGREDIENT_HYPHEN_SUFFIXES = frozenset(
    {
        "associated",
        "based",
        "containing",
        "derived",
        "enriched",
        "induced",
        "loaded",
        "mediated",
        "related",
        "treated",
    }
)
_NON_ASCII_LETTER_PATTERN = re.compile(r"[^\x00-\x7f]")


class PubmedSelectionPolicy:
    def __init__(self, max_papers_per_ingredient: int = DEFAULT_MAX_PAPERS_PER_INGREDIENT) -> None:
        if not 1 <= max_papers_per_ingredient <= MAX_PAPERS_HARD_LIMIT:
            raise ValueError(
                f"max_papers_per_ingredient 는 1~{MAX_PAPERS_HARD_LIMIT} 이어야 합니다"
                f"(받은 값: {max_papers_per_ingredient}). compact corpus 는 성분당 소수만 수집합니다."
            )
        self.max_papers_per_ingredient = max_papers_per_ingredient
        self._designs = StudyDesignClassifier()
        self._routes = RouteClassifier()
        self._directness = DirectnessClassifier()
        self._skin = SkinRelevanceClassifier()
        self._topics = ClaimTopicClassifier()

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
        """PubMed 는 영문 색인이라 한글 등 비ASCII 표기는 제외한다.

        `ingredient.aliases` 는 exact-equivalent 표기만 담는다는 계약이다(CollectionIngredient 참고).
        family·파생형·계열명 용어는 이 입력으로 들어오지 않아야 하며, 여기서 임의로 덧붙이지도 않는다.
        """
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

    def _rank_key(self, assessment: PubmedAssessment) -> tuple[int, int, int, int]:
        year = assessment.record.publication_date.year if assessment.record.publication_date else 0
        # 등급(단일 직접 → 리뷰 → 복합) → 점수 높은 순 → 최신 순 → PMID 오름차순(재실행 시 순서가 흔들리지 않게)
        return (
            _GRADE_ORDER[assessment.evidence_grade],
            -assessment.score,
            -year,
            int(assessment.record.pmid),
        )

    def assess_record(
        self, ingredient: CollectionIngredient, record: PubmedRecord
    ) -> PubmedAssessment:
        """예산과 무관하게 record 한 편을 단독 평가한다(버려진 record 의 사유를 남길 때 쓴다)."""
        return self._assess_one(ingredient, record)

    def _assess_one(
        self, ingredient: CollectionIngredient, record: PubmedRecord
    ) -> PubmedAssessment:
        names = self.search_names(ingredient)
        design = self._designs.classify(record)
        study_type = self._designs.to_storage_type(design)
        route = self._routes.classify(record, design)
        role = self._directness.classify(record, names)
        skin = self._skin.classify(record)
        formulation = self.classify_formulation(record, names)
        topics = self._topics.classify(record)
        title_mentioned = self._mentions(names, record.title)
        score = self._score(record, names, study_type, formulation, topics, title_mentioned)

        disposition, reason = self._decide(
            record,
            names,
            design,
            route,
            role,
            skin,
            formulation,
            topics,
            title_mentioned,
            score,
        )
        grade = EvidenceGrade.NOT_GRADED
        if disposition is PubmedSelectionDisposition.SELECTED:
            grade = self._grade(design, formulation)
        elif reason is PubmedSelectionReason.COMBINATION_REQUIRES_ASSOCIATION_MAPPING:
            grade = EvidenceGrade.COMBINATION_TOPICAL_HUMAN
        return PubmedAssessment(
            ingredient_id=ingredient.ingredient_id,
            record=record,
            study_type=study_type,
            formulation_type=formulation,
            claim_topics=topics,
            score=score,
            disposition=disposition,
            reason=reason,
            route=route,
            study_design=design,
            ingredient_role=role,
            skin_relevance=skin,
            evidence_grade=grade,
        )

    def _grade(self, design: StudyDesign, formulation: EvidenceFormulationType) -> EvidenceGrade:
        if formulation is EvidenceFormulationType.COMBINATION_FORMULATION:
            # 복합 제형은 이 성분의 기여를 논문에서 분리할 수 없어 단일 성분 직접 근거로 올리지 않는다
            return EvidenceGrade.COMBINATION_TOPICAL_HUMAN
        if design is StudyDesign.REVIEW:
            return EvidenceGrade.TOPICAL_REVIEW
        return EvidenceGrade.DIRECT_SINGLE_TOPICAL_HUMAN

    def _decide(
        self,
        record: PubmedRecord,
        names: list[str],
        design: StudyDesign,
        route: AdministrationRoute,
        role: IngredientRole,
        skin: SkinRelevance,
        formulation: EvidenceFormulationType,
        topics: list[EvidenceClaimTopic],
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
        # 성분 이름만 걸린 비피부 논문은 버린다(예: cystinosis, 내분비 독성 연구)
        if skin is SkinRelevance.NOT_RELEVANT:
            return rejected, PubmedSelectionReason.NOT_SKIN_RELEVANT
        if design is StudyDesign.MIXED_HUMAN_AND_LAB:
            return candidate, PubmedSelectionReason.MIXED_DESIGN_REVIEW
        if design not in _SELECTABLE_DESIGNS:
            return candidate, PubmedSelectionReason.NON_CLINICAL_STUDY_DESIGN
        if route in (AdministrationRoute.ORAL, AdministrationRoute.INJECTION):
            return candidate, PubmedSelectionReason.ROUTE_NOT_TOPICAL
        if route is not AdministrationRoute.TOPICAL:
            return candidate, PubmedSelectionReason.ROUTE_UNCLEAR
        if role is IngredientRole.COMPARATOR_OR_BACKGROUND:
            return candidate, PubmedSelectionReason.COMPARATOR_ONLY
        if not title_mentioned:
            return candidate, PubmedSelectionReason.INGREDIENT_NOT_IN_TITLE
        if not topics:
            # abstract 가 지지하는 topic 을 못 찾으면 임의로 만들지 않고 자동 selected 도 하지 않는다
            return candidate, PubmedSelectionReason.NO_CLAIM_TOPIC
        if score < _MIN_SELECT_SCORE:
            return candidate, PubmedSelectionReason.STUDY_TYPE_NOT_SELECTABLE
        if formulation is EvidenceFormulationType.COMBINATION_FORMULATION:
            # 자동 수집 입력은 현재 성분 ID만 알기 때문에 여기서 selected로 만들면 Backend가
            # 단일 성분 Evidence로 오해한다. 복수 표준 ID를 사람이 확정한 뒤 association으로 적재한다.
            return candidate, PubmedSelectionReason.COMBINATION_REQUIRES_ASSOCIATION_MAPPING
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
        if formulation is EvidenceFormulationType.COMBINATION_FORMULATION:
            score -= _COMBINATION_PENALTY
        return score

    # ----------------------------------------------------------- classification

    def classify_study_type(self, record: PubmedRecord) -> EvidenceStudyType:
        return self._designs.to_storage_type(self._designs.classify(record))

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
            if self._has_hyphenated_compound(title, escaped):
                return EvidenceFormulationType.COMBINATION_FORMULATION
        return EvidenceFormulationType.SINGLE_INGREDIENT

    def _has_hyphenated_compound(self, title: str, escaped_name: str) -> bool:
        trailing = re.search(
            rf"{escaped_name}\s*[-–—]\s*(?P<term>[A-Za-z][A-Za-z0-9]*)",
            title,
            re.IGNORECASE,
        )
        if trailing is not None:
            return trailing.group("term").casefold() not in _NON_INGREDIENT_HYPHEN_SUFFIXES
        return bool(
            re.search(
                rf"[A-Za-z][A-Za-z0-9]*\s*[-–—]\s*{escaped_name}",
                title,
                re.IGNORECASE,
            )
        )

    def _mentions(self, names: list[str], *texts: str) -> bool:
        haystack = " ".join(texts)
        return any(
            re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", haystack, re.IGNORECASE)
            for name in names
        )
