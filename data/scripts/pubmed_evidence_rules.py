"""PubMed record 를 "이 성분의 국소 피부 직접 근거인가" 관점에서 분류하는 결정적 규칙. 네트워크·LLM 없음.

smoke 10 에서 확인된 오류(경구·주사 논문 선택, 세포 실험의 human 오분류, 비교 대조로만 등장한 성분,
비피부 논문 통과)를 막기 위한 분류기 묶음이다. 각 분류기는 근거가 부족하면 UNCLEAR 를 돌려주고,
호출한 정책은 UNCLEAR 를 통과시키지 않는다(불확실을 국소·인체·직접 근거로 간주하지 않는다).
"""

import re

from data.scripts.evidence_collector_schemas import (
    AdministrationRoute,
    IngredientRole,
    PubmedRecord,
    SkinRelevance,
    StudyDesign,
)
from models.evidence_document import EvidenceClaimTopic, EvidenceStudyType

_FLAGS = re.IGNORECASE

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
_REVIEW_PUBLICATION_TYPES = frozenset({"systematic review", "meta-analysis", "review"})


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(patterns), _FLAGS)


# ---------------------------------------------------------------- study design

# 사람 대상 임상 연구의 문장 단서. "Humans" MeSH 는 사람 세포 실험에도 붙어서 단독으로는 쓰지 않는다.
_HUMAN_SUBJECT = _rx(
    r"\bparticipants?\b",
    r"\bvolunteers?\b",
    r"\bpatients?\b",
    r"\bsubjects?\b",
    r"\b(?:women|men|adults|children)\b",
)
_CLINICAL_DESIGN = _rx(
    r"\brandomi[sz]ed\b",
    r"\brandomly\b",
    r"\bplacebo\b",
    r"\bvehicle-controlled\b",
    r"\bsplit[- ]face\b",
    r"\bopen[- ]label\b",
    r"\bclinical (?:trial|study)\b",
    r"\bdouble[- ]blind",
)
_IN_VITRO = _rx(
    r"\bin[- ]vitro\b",
    r"\bcultured\b",
    r"\bco-?cultur",
    r"\bcell lines?\b",
    r"\bkeratinocytes\b",
    r"\bfibroblasts\b",
    r"\bproteom",
    r"\bcytotox",
    r"\bnanocomposite",
    # 제형 개발·캡슐화 논문의 실험실 단서(임상 pubtype 이 붙어도 human 근거가 아니다)
    r"\bencapsulat",
    r"\bentrapment\b",
    r"\bparticle size\b",
    r"\brelease (?:kinetics|profile|rate)s?\b",
    r"\bfranz\b",
    r"\bsol-gel\b",
    r"\bMTT\b",
    r"\bHaCaT\b",
)
_EX_VIVO = _rx(r"\bex[- ]vivo\b", r"\bexplants?\b")
_ANIMAL = _rx(
    r"\bmice\b",
    r"\bmouse\b",
    r"\brats?\b",
    r"\bmurine\b",
    r"\brabbits?\b",
    r"\bguinea pigs?\b",
    r"\bzebrafish\b",
)


class StudyDesignClassifier:
    """키워드 하나로 human 을 판정하지 않는다: 임상 설계 단서와 사람 대상 단서가 함께 있어야 한다."""

    def classify(self, record: PubmedRecord) -> StudyDesign:
        publication_types = {value.lower() for value in record.publication_types}
        mesh = {value.lower() for value in record.mesh_terms}
        text = f"{record.title} {record.abstract or ''}"
        if publication_types & _REVIEW_PUBLICATION_TYPES:
            return StudyDesign.REVIEW

        is_clinical = bool(publication_types & _TRIAL_PUBLICATION_TYPES) or (
            bool(_HUMAN_SUBJECT.search(text)) and bool(_CLINICAL_DESIGN.search(text))
        )
        has_ex_vivo = bool(_EX_VIVO.search(text))
        has_in_vitro = bool(_IN_VITRO.search(text)) or "in vitro techniques" in mesh
        if is_clinical:
            # 임상 시험 + 실험실 단서가 함께 있으면 섞인 연구로 표시해 human 단독 근거로 과장하지 않는다
            if has_ex_vivo or has_in_vitro:
                return StudyDesign.MIXED_HUMAN_AND_LAB
            return StudyDesign.HUMAN_CLINICAL
        if "animals" in mesh or _ANIMAL.search(text):
            return StudyDesign.ANIMAL
        if has_ex_vivo:
            return StudyDesign.EX_VIVO
        if has_in_vitro:
            return StudyDesign.IN_VITRO
        return StudyDesign.UNCLEAR

    def to_storage_type(self, design: StudyDesign) -> EvidenceStudyType:
        """DB enum 에는 ex_vivo 가 없다(마이그레이션 금지). in_vitro 로 접는다."""
        return {
            StudyDesign.HUMAN_CLINICAL: EvidenceStudyType.HUMAN_STUDY,
            StudyDesign.MIXED_HUMAN_AND_LAB: EvidenceStudyType.MIXED_IN_VITRO_AND_HUMAN,
            StudyDesign.ANIMAL: EvidenceStudyType.ANIMAL_STUDY,
            StudyDesign.IN_VITRO: EvidenceStudyType.IN_VITRO,
            StudyDesign.EX_VIVO: EvidenceStudyType.IN_VITRO,
            StudyDesign.REVIEW: EvidenceStudyType.REVIEW,
            StudyDesign.UNCLEAR: EvidenceStudyType.UNKNOWN,
        }[design]


# ----------------------------------------------------------------------- route

_ORAL_CAVITY = (
    r"(?!\s+(?:cavity|wound|mucos|pathogen|antisep|health|care|hygiene|lichen|surgery|bacteria))"
)
_TOPICAL_MESH = frozenset({"administration, topical", "administration, cutaneous"})
_ORAL_MESH = frozenset({"administration, oral", "dietary supplements"})
_INJECTION_MESH = frozenset(
    {
        "injections, intradermal",
        "injections, subcutaneous",
        "injections, intralesional",
        "injections",
    }
)
_TOPICAL_TERMS = _rx(
    r"\btopical(?:ly)?\b",
    r"\bcream\b",
    r"\bserum\b",
    r"\bgel\b",
    r"\blotion\b",
    r"\bointment\b",
    r"\bmoisturi[sz]er\b",
    r"\bvehicle\b",
    r"\bsplit[- ]face\b",
    r"\bapplied\b",
    r"\bapplication\b",
    r"\bchemical peel",
    r"\bemulsion\b",
    r"\bmask\b",
    r"\bpeel(?:s|ing)?\b",
    r"\bshampoo\b",
    r"\bwipes?\b",
    r"\bsunscreen",
)
_ORAL_TERMS = _rx(
    rf"\boral(?:ly)?\b{_ORAL_CAVITY}",
    r"\bsupplement(?:ation|s|ed)?\b",
    r"\bingest",
    r"\bcapsules?\b",
    r"\btablets?\b",
    r"\bdietary\b",
    r"\bnutricosmetic",
    r"\bdrink\b",
)
_INJECTION_TERMS = _rx(
    r"\binject",
    r"\bintradermal\b",
    r"\bsubcutaneous\b",
    r"\bmesotherap",
    r"\bintravenous\b",
    r"\bintralesional\b",
)


class RouteClassifier:
    """투여 경로 판별. 제목 단서가 우선이고, 판별 불가는 UNCLEAR 로 남긴다(topical 로 간주하지 않는다)."""

    def classify(self, record: PubmedRecord, design: StudyDesign) -> AdministrationRoute:
        if design in (StudyDesign.IN_VITRO, StudyDesign.EX_VIVO, StudyDesign.ANIMAL):
            return AdministrationRoute.NOT_APPLICABLE
        mesh = {value.lower() for value in record.mesh_terms}
        title_routes = self._routes(record.title, frozenset())
        if len(title_routes) == 1:
            return next(iter(title_routes))
        if len(title_routes) > 1:
            return AdministrationRoute.UNCLEAR
        routes = self._routes(record.abstract or "", mesh)
        if len(routes) == 1:
            return next(iter(routes))
        return AdministrationRoute.UNCLEAR

    def _routes(self, text: str, mesh: frozenset[str] | set[str]) -> set[AdministrationRoute]:
        routes: set[AdministrationRoute] = set()
        if _TOPICAL_TERMS.search(text) or mesh & _TOPICAL_MESH:
            routes.add(AdministrationRoute.TOPICAL)
        if _ORAL_TERMS.search(text) or mesh & _ORAL_MESH:
            routes.add(AdministrationRoute.ORAL)
        if _INJECTION_TERMS.search(text) or mesh & _INJECTION_MESH:
            routes.add(AdministrationRoute.INJECTION)
        return routes


# ------------------------------------------------------------------ directness

_COMPARATOR_LEAD = (
    r"(?:outperforms?|outperformed|superior to|inferior to|versus|vs\.?|compared (?:to|with)|"
    r"than|instead of|replacing|replacement for|alternative to|against)"
)


class DirectnessClassifier:
    """성분이 실제 시험 대상인지, 비교 대조/배경으로만 언급됐는지 본다."""

    def classify(self, record: PubmedRecord, names: list[str]) -> IngredientRole:
        title_hits = [name for name in names if self._mentions(name, record.title)]
        if title_hits:
            if all(self._is_comparator(name, record.title) for name in title_hits):
                return IngredientRole.COMPARATOR_OR_BACKGROUND
            return IngredientRole.INTERVENTION
        abstract = record.abstract or ""
        abstract_hits = [name for name in names if self._mentions(name, abstract)]
        if abstract_hits and all(self._is_comparator(name, abstract) for name in abstract_hits):
            return IngredientRole.COMPARATOR_OR_BACKGROUND
        return IngredientRole.UNCLEAR

    def _mentions(self, name: str, text: str) -> bool:
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, _FLAGS))

    def _is_comparator(self, name: str, text: str) -> bool:
        """성분 앞 3단어 안에 비교 대조 표현이 있으면 그 언급은 comparator 로 본다."""
        pattern = re.compile(
            rf"{_COMPARATOR_LEAD}\s+(?:[\w\-']+\s+){{0,3}}?(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])",
            _FLAGS,
        )
        mention = re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", _FLAGS)
        mentions = len(mention.findall(text))
        return mentions > 0 and len(pattern.findall(text)) >= mentions


# --------------------------------------------------------------- skin relevance

_SKIN_TERMS = _rx(
    r"\bskin\b",
    r"\bdermal\b",
    r"\bdermis\b",
    r"\bepiderm",
    r"\bcutaneous\b",
    r"\bdermat",
    r"\bcosmetic",
    r"\bwrinkle",
    r"\bacne\b",
    r"\bmelasma\b",
    r"\bchloasma\b",
    r"\bhyperpigment",
    r"\bphotoag",
    r"\bfacial\b",
    r"\bsebum\b",
    r"\beczema\b",
    r"\brosacea\b",
    r"\bpsoriasis\b",
    r"\bcrow'?s feet\b",
    r"\bscar(?:s|ring)?\b",
    r"\blaceration",
    r"\bstretch marks?\b",
    r"\bseborrh",
    r"\bscalp\b",
    # 구강·구개 상처는 피부가 아니다
    r"(?<!oral )(?<!palatal )(?<!gingival )(?<!dental )\bwounds?\b",
)
_SKIN_MESH = frozenset(
    {"skin", "skin aging", "face", "dermatology", "skin diseases", "skin physiological phenomena"}
)
_MIN_ABSTRACT_SKIN_HITS = 2


class SkinRelevanceClassifier:
    """제목/MeSH 에 피부 맥락이 있거나, 초록에 서로 다른 피부 용어가 2개 이상 있어야 한다.

    "cultured cystinotic skin fibroblasts" 처럼 skin 이 한 번 스치기만 하는 논문은 통과시키지 않는다.
    """

    def classify(self, record: PubmedRecord) -> SkinRelevance:
        mesh = {value.lower() for value in record.mesh_terms}
        if _SKIN_TERMS.search(record.title) or mesh & _SKIN_MESH:
            return SkinRelevance.RELEVANT
        distinct = {m.group(0).lower() for m in _SKIN_TERMS.finditer(record.abstract or "")}
        if len(distinct) >= _MIN_ABSTRACT_SKIN_HITS:
            return SkinRelevance.RELEVANT
        return SkinRelevance.NOT_RELEVANT


# ---------------------------------------------------------------- claim topics

# abstract 가 실제로 다루는 주제만 연결한다. title 만 맞고 abstract 에 없으면 연결하지 않는다.
_CLAIM_TOPIC_PATTERNS: dict[EvidenceClaimTopic, re.Pattern[str]] = {
    EvidenceClaimTopic.EFFICACY: _rx(
        r"wrinkle",
        r"hyperpigment",
        r"melasma",
        r"chloasma",
        r"barrier",
        r"sebum",
        r"acne",
        r"moistur",
        r"hydrat",
        r"elasticity",
        r"brighten",
        r"pigmentation",
        r"anti-aging",
        r"photoaging",
        r"\befficacy\b",
        r"\beffective\b",
        r"\bimprov",
        r"significantly (?:reduc|decreas|increas)",
    ),
    EvidenceClaimTopic.PRECAUTION: _rx(
        r"irritat",
        r"sensiti[sz]",
        r"allerg",
        r"adverse (?:event|reaction|effect)",
        r"tolerab",
        r"safety (?:profile|assessment|evaluation)",
        r"(?:efficacy and|and) safety",
    ),
}


class ClaimTopicClassifier:
    def classify(self, record: PubmedRecord) -> list[EvidenceClaimTopic]:
        abstract = record.abstract or ""
        return [
            topic for topic, pattern in _CLAIM_TOPIC_PATTERNS.items() if pattern.search(abstract)
        ]
