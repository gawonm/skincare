"""audit universe(2,872)를 baseline 수집 대상으로 써도 되는지 가르는 수집 자격 규칙과 family 후보 탐지.

읽기 전용이며 외부 API 호출·수집·embedding·DB write 를 하지 않는다. 결과는 "제안"이고, 이름 규칙 +
기존 NIA/제품/근거 수만 쓴다(LLM 없음). 규칙은 사람이 QA 하기 쉽게 정규식 목록으로 남긴다.

사용법:
    uv run python -m data.scripts.evidence_collection_universe \
        --database-url postgresql+asyncpg://app:app@localhost:5432/skincare_v4_final \
        --nia-summary <nia_ingredient_relevance_summary.csv>
"""

import argparse
import asyncio
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from data.scripts.evidence_collector_schemas import CollectionIngredient
from data.scripts.evidence_coverage_audit import CoverageAuditRunner, CoverageCsvWriter
from data.scripts.evidence_coverage_schemas import (
    CollectionDecision,
    CoverageRow,
    Decision,
    FamilyMemberRow,
    PriorityTier,
    ReviewFlag,
    SafetyRegistryEntry,
    SafetyReviewStatus,
    UniverseCategory,
    UniverseRow,
)
from models.ingredient import IngredientMaster

# 제품 근거가 이 수 이상이거나 NIA 언급이 있어야 baseline 수집 대상으로 본다. 제품 1~4개짜리 long tail 은
# 수집해도 상담에서 쓰일 일이 드물어 DEFER 한다(임의 기준이며 사람 확인이 필요하다).
MIN_PRODUCTS_FOR_BASELINE = 5
QA_NIA_MIN_CASES = 170  # coverage audit 의 NIA 높음 기준과 같은 값
QA_ACTIVE_MIN_PRODUCTS = 100  # coverage audit 의 제품 높음 기준과 같은 값

_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
_UNIVERSE_FILENAME = "collection_universe.csv"
_FAMILY_FILENAME = "ingredient_family_candidates.csv"
_QA_SAMPLE_FILENAME = "collection_universe_qa_sample.csv"
_SAFETY_REGISTRY_PATH = Path("docs/data/safety_review_registry.json")


class FamilyRule(BaseModel):
    """query expansion 전용 family. canonical ingredient_id 를 합치지 않는다."""

    model_config = ConfigDict(frozen=True)

    name: str
    pattern: str
    expansion_terms: tuple[str, ...]
    attribution_note: str


FAMILY_RULES: tuple[FamilyRule, ...] = (
    FamilyRule(
        name="hyaluronic",
        pattern=r"hyaluron",
        expansion_terms=("hyaluronic acid", "hyaluronan", "sodium hyaluronate"),
        attribution_note="분자량·염·가교 형태별로 결과가 달라 논문이 'hyaluronic acid'만 말하면 파생형에 자동 귀속하지 않는다",
    ),
    FamilyRule(
        name="aloe",
        pattern=r"\baloe\b",
        expansion_terms=("aloe vera", "Aloe barbadensis", "aloe gel"),
        attribution_note="잎즙·추출물·분말·캘러스가 다른 물질이라 'aloe vera' 일반 논문은 특정 형태에 자동 귀속하지 않는다",
    ),
    FamilyRule(
        name="centella",
        pattern=r"centella|madecass|asiatic",
        expansion_terms=("Centella asiatica", "gotu kola", "madecassoside", "asiaticoside"),
        attribution_note="추출물과 madecassoside/asiaticoside 등 단일 성분은 별개다. 추출물 논문을 단일 성분 근거로 쓰지 않는다",
    ),
    FamilyRule(
        name="vitamin_c",
        pattern=r"ascorb",
        expansion_terms=("ascorbic acid", "vitamin C", "L-ascorbic acid"),
        attribution_note="L-ascorbic acid 논문 결과를 안정화 유도체(3-O-ethyl, ascorbyl phosphate 등)에 그대로 귀속하지 않는다",
    ),
    FamilyRule(
        name="retinoid",
        pattern=r"^retin|retinyl|retinal\b|retinoate|adapalene|tretinoin",
        expansion_terms=("retinol", "retinoid", "retinyl palmitate", "retinaldehyde"),
        attribution_note="retinoid 계열 효능·자극 결과는 성분별 강도가 달라 retinol 논문을 다른 retinoid 에 귀속하지 않는다",
    ),
    FamilyRule(
        name="bha_aha",
        pattern=r"salicylic|glycolic|^lactic acid|mandelic|gluconolactone|lactobionic|malic acid|tartaric|^bha$|^aha$",
        expansion_terms=(
            "salicylic acid",
            "beta hydroxy acid",
            "glycolic acid",
            "alpha hydroxy acid",
        ),
        attribution_note="BHA/AHA 는 계열명이다. 'BHA' 토큰은 butylated hydroxyanisole 일 수도 있어 계열명 검색 결과를 개별 산에 귀속하지 않는다",
    ),
)

# 사람이 이미 정한 결정. Tier A manual review + 이번 추가 결정(Salicylic/Ascorbic Acid).
MANUAL_DECISIONS: dict[str, tuple[CollectionDecision, str]] = {
    "Collagen": (CollectionDecision.QA_PRIORITY, "manual review INCLUDE"),
    "3-O-Ethyl Ascorbic Acid": (CollectionDecision.QA_PRIORITY, "manual review INCLUDE"),
    "Centella Asiatica Extract": (CollectionDecision.QA_PRIORITY, "manual review INCLUDE"),
    "Retinol": (CollectionDecision.QA_PRIORITY, "manual review INCLUDE(threshold 참고)"),
    "Salicylic Acid": (
        CollectionDecision.QA_PRIORITY,
        "threshold 누락 사례 검토: 제품 178·NIA 3·근거 0, BHA 계열 대표 산",
    ),
    "Ascorbic Acid": (
        CollectionDecision.QA_PRIORITY,
        "threshold 누락 사례 검토: 제품 179·NIA 36·근거 0, 비타민C 계열 대표",
    ),
    "Hexapeptide-2": (
        CollectionDecision.DEFER,
        "INCLUDE 승격 보류: candidate discovery smoke 샘플로만 사용",
    ),
    "Sulfur": (CollectionDecision.DEFER, "manual review DEFER"),
    "Elastin": (CollectionDecision.DEFER, "manual review DEFER"),
    "Arctium Lappa Root Extract": (CollectionDecision.DEFER, "manual review DEFER"),
    "Aloe Barbadensis Leaf Juice Powder": (
        CollectionDecision.DEFER,
        "manual review DEFER: 알로에 계열 단위 미정",
    ),
    "Squalane": (CollectionDecision.DEFER, "manual review DEFER"),
    "Sodium Hyaluronate": (
        CollectionDecision.DEFER,
        "manual review DEFER: 히알루론산 계열 단위 미정(smoke 대상)",
    ),
    "Tocopherol": (CollectionDecision.DEFER, "manual review DEFER"),
    "Beta-Glucan": (CollectionDecision.DEFER, "manual review DEFER"),
    "Mineral Salts": (
        CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
        "manual review EXCLUDE",
    ),
    "Melanin": (CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION, "manual review EXCLUDE"),
    "Tyrosinase": (CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION, "manual review EXCLUDE"),
    "BHA": (
        CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
        "manual review EXCLUDE: 계열명/butylated hydroxyanisole 모호(negative control)",
    ),
    "Momordica Charantia Fruit Extract": (
        CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
        "manual review EXCLUDE",
    ),
    "Carapa Guianensis Seed Oil": (
        CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
        "manual review EXCLUDE",
    ),
}

# 이름·유형이 서로 다른 성분으로 collector 가 각 유형을 어떻게 처리해야 하는지 보는 smoke 표본.
SMOKE_INGREDIENTS: tuple[str, ...] = (
    "Niacinamide",  # 좋은 active, 기존 근거 있음
    "Retinol",  # active + retinoid family
    "Salicylic Acid",  # BHA 계열 대표
    "Ascorbic Acid",  # vitamin C 원형
    "3-O-Ethyl Ascorbic Acid",  # vitamin C 유도체
    "Sodium Ascorbyl Phosphate",  # vitamin C 유도체(귀속 주의)
    "Centella Asiatica Extract",  # botanical 추출물
    "Madecassoside",  # 추출물 유래 단일 성분
    "Hyaluronic Acid",  # family 원형
    "Sodium Hyaluronate",  # family 유도체
    "Hexapeptide-2",  # 검색 가능성/noise 확인
    "Collagen",  # 단백질, 국소 효능 한계
    "Acetyl Hexapeptide-8",  # 펩타이드
    "Curcuma Longa (Turmeric) Root Extract",  # 일반 botanical
    "Tocopherol",  # 보조 성분(기존 CIR 있음)
    "Glycerin",  # base negative control
    "Melanin",  # 기전 용어 negative control
    "BHA",  # 모호 용어 negative control
)


def _rx(*words: str) -> re.Pattern[str]:
    return re.compile("|".join(words), re.IGNORECASE)


_AMINO_ACIDS = (
    "glycine|serine|alanine|proline|arginine|glutamic acid|lysine|threonine|aspartic acid|"
    "histidine|valine|leucine|isoleucine|phenylalanine|tyrosine|betaine"
)

# 위에서부터 처음 맞는 규칙이 이긴다. 순서가 곧 우선순위다(예: 히알루론산 가교체는 polymer 가 아니라 active).
_CATEGORY_RULES: tuple[tuple[UniverseCategory, re.Pattern[str]], ...] = (
    (
        UniverseCategory.FAMILY_OR_MECHANISM_TERM,
        _rx(r"^bha$", r"^aha$", r"^melanin$", r"^tyrosinase$", r"^mineral salts$"),
    ),
    (
        # preservative 의 "benzoate" 보다 먼저 봐야 Diethylamino Hydroxybenzoyl Hexyl Benzoate 같은 UV 필터가 안 잘린다
        UniverseCategory.UV_FILTER,
        _rx(
            r"triazine",
            r"benzophenone",
            r"dibenzoylmethane",
            r"octocrylene",
            r"methoxycinnamate",
            r"trimethoxycinnamate",
            r"homosalate",
            r"ethylhexyl salicylate",
            r"^titanium dioxide$",
            r"^zinc oxide$",
            r"diethylamino hydroxybenzoyl",
            r"drometrizole",
            r"ensulizole",
            r"bemotrizinol",
        ),
    ),
    (
        UniverseCategory.PEPTIDE_OR_PROTEIN,
        _rx(
            r"peptide", r"collagen", r"elastin", r"protein", r"keratin", r"albumen", r"^sodium dna$"
        ),
    ),
    (UniverseCategory.ACTIVE_OR_FUNCTIONAL, _rx(r"hyaluron")),
    (
        UniverseCategory.FILLER_POWDER,
        _rx(
            r"nitride",
            r"^talc$",
            r"^kaolin$",
            r"alumina",
            r"bismuth",
        ),
    ),
    (
        UniverseCategory.PRESERVATIVE_STABILIZER,
        _rx(
            r"edta",
            r"phytate",
            r"phenoxyethanol",
            r"benzoate",
            r"sorbate",
            r"hydroxyacetophenone",
            r"ethylhexylglycerin",
            r"caprylyl glycol",
            r"glyceryl caprylate",
            r"1,2-hexanediol",
            r"chlorphenesin",
            r"paraben",
            r"benzyl alcohol",
            r"dehydroacetic",
        ),
    ),
    (
        UniverseCategory.PH_ADJUSTER_SALT,
        _rx(
            r"^citric acid$",
            r"sodium citrate",
            r"hydroxide",
            r"tromethamine",
            r"^sodium chloride$",
            r"triethanolamine",
            r"sodium phosphate",
        ),
    ),
    (
        UniverseCategory.FORMULATION_AID,
        _rx(
            r"citrate$",
            r"butyloctyl",
            r"propylene carbonate",
            r"dicaprylyl carbonate",
            r"^poloxamer",
            r"^alcohol",
        ),
    ),
    (
        UniverseCategory.FRAGRANCE_ALLERGEN,
        _rx(
            r"^limonene$",
            r"^linalool$",
            r"^citronellol$",
            r"^geraniol$",
            r"^eugenol$",
            r"^citral$",
            r"^coumarin$",
            r"^benzyl salicylate$",
            r"hexyl cinnamal",
            r"isomethyl ionone",
            r"^farnesol$",
            r"^hydroxycitronellal$",
        ),
    ),
    (
        UniverseCategory.POLYMER_THICKENER,
        _rx(
            r"carbomer",
            r"\bgum\b",
            r"crosspolymer",
            r"copolymer",
            r"acrylate",
            r"polyacryl",
            r"cellulose",
            r"dimethicone",
            r"methicone",
            r"siloxane",
            r"silsesquioxane",
            r"polydecene",
            r"^silica$",
            r"dextrin",
            r"polyquaternium",
            r"starch",
            r"\bagar\b",
            r"^algin$",
            r"alginate",
            r"carrageenan",
            r"pectin",
            r"pullulan",
            r"polymer",
        ),
    ),
    (
        UniverseCategory.SURFACTANT_EMULSIFIER_EMOLLIENT,
        _rx(
            r"stearate",
            r"stearyl",
            r"cetearyl",
            r"^cetyl",
            r"behenyl",
            r"polyglyceryl",
            r"sorbitan",
            r"olivate",
            r"glucoside",
            r"cocoyl",
            r"isethionate",
            r"lecithin",
            r"triglyceride",
            r"ethylhexanoate",
            r"palmitate",
            r"triethylhexanoin",
            r"alketh",
            r"glycereth",
            r"laureth",
            r"\bpeg-",
            r"\bppg-",
            r"polysorbate",
            r"myristate",
            r"isostearate",
            r"^(stearic|palmitic|myristic|lauric) acid$",
            r"oleate",
            r"laurate",
            r"caprylate",
            r"behenate",
            r"isononanoate",
            r"eth-\d",
            r"(heptanoate|dicaprate|decanoate|hexanoate|octanoate|hexacaprylate)$",
            r"hexyldecanol",
            r"octyldodecanol",
            r"isododecane",
            r"isohexadecane",
            r"tridecane",
            r"triheptanoin",
            r"paraffin",
            r"petrolatum",
            r"^glass$",
            r"^mica$",
            r"ultramarine",
            r"iron oxide",
            r"chromium oxide",
        ),
    ),
    (
        UniverseCategory.BASE_SOLVENT_HUMECTANT,
        _rx(
            r"(diol|glycol)$",
            r"^glycerin$",
            r"^glucose$",
            r"^trehalose$",
            r"^xylitol$",
            r"^sorbitol$",
            r"fructooligosaccharides",
            rf"^({_AMINO_ACIDS})$",
        ),
    ),
    (UniverseCategory.CARRIER_OIL, _rx(r"\boil$", r"\bbutter$")),
    (
        UniverseCategory.BOTANICAL_OR_FERMENT,
        _rx(
            r"\bextract\b",
            r"\boil\b",
            r"\bbutter\b",
            r"\bferment\b",
            r"\blysate\b",
            r"\bjuice\b",
            r"\bpowder\b",
            r"\bcallus\b",
            r"\bfiltrate\b",
            r"\bwater\b",
            r"\bresin\b",
            r"\bbran\b",
        ),
    ),
)

# 제형 기능이 주된 역할이라 자동 수집하지 않는 범주. NIA 언급이 있으면 DEFER, 없으면 EXCLUDE.
_FORMULATION_CATEGORIES = frozenset(
    {
        UniverseCategory.PRESERVATIVE_STABILIZER,
        UniverseCategory.POLYMER_THICKENER,
        UniverseCategory.SURFACTANT_EMULSIFIER_EMOLLIENT,
        UniverseCategory.PH_ADJUSTER_SALT,
        UniverseCategory.FILLER_POWDER,
        UniverseCategory.FORMULATION_AID,
    }
)
# 식물성 범주는 NIA 언급 또는 기존 근거가 있어야 baseline 후보가 된다(제품 수 단독 gate 는 QA 에서 기각됐다).
_PLANT_CATEGORIES = frozenset({UniverseCategory.BOTANICAL_OR_FERMENT, UniverseCategory.CARRIER_OIL})
# 자극성 세정 계면활성제. blanket EXCLUDE 대신 안전성 근거 가치가 있는 항목으로 남긴다.
_IRRITANT_SURFACTANT = _rx(r"(laureth|lauryl|myreth|deceth).*sulfate$")


class SafetyReviewRegistry:
    """curated safety-review registry(JSON). 파일이 없으면 조용히 넘어가지 않고 실패한다."""

    def __init__(self, entries: list[SafetyRegistryEntry]) -> None:
        self._by_id = {e.ingredient_id: e for e in entries}

    @classmethod
    def load(cls, path: Path) -> "SafetyReviewRegistry":
        if not path.exists():
            raise RuntimeError(f"safety-review registry 파일이 없습니다: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls([SafetyRegistryEntry.model_validate(e) for e in raw])

    def get(self, ingredient_id: UUID) -> SafetyRegistryEntry | None:
        return self._by_id.get(ingredient_id)

    def without_approvals(self) -> "SafetyReviewRegistry":
        """QA 표본에 맞춰 승인한 항목을 뺀 규칙 단독 평가용(과적합 확인)."""
        return SafetyReviewRegistry(
            [e for e in self._by_id.values() if e.status is not SafetyReviewStatus.APPROVED]
        )


class CollectionEligibility:
    """카테고리와 수집 자격을 규칙으로 정한다. 같은 입력이면 같은 결과가 나온다."""

    def __init__(self, registry: SafetyReviewRegistry | None = None) -> None:
        self._registry = registry or SafetyReviewRegistry([])

    def category(self, name: str) -> UniverseCategory:
        for category, pattern in _CATEGORY_RULES:
            if pattern.search(name):
                return category
        return UniverseCategory.ACTIVE_OR_FUNCTIONAL

    def decide(self, row: CoverageRow, category: UniverseCategory) -> Decision:
        manual = MANUAL_DECISIONS.get(row.ingredient_name)
        if manual is not None:
            return Decision(decision=manual[0], reason=manual[1])
        entry = self._registry.get(row.ingredient_id)
        if entry is not None and entry.status is SafetyReviewStatus.APPROVED:
            return Decision(
                decision=CollectionDecision.COLLECT_BASELINE,
                reason=f"safety-review registry 승인({entry.group}): {entry.note}",
                flags=(ReviewFlag.SAFETY_RELEVANT,),
            )
        flags = (
            (ReviewFlag.SAFETY_REVIEW_CANDIDATE,)
            if entry is not None and entry.status is SafetyReviewStatus.CANDIDATE
            else ()
        )
        if category is UniverseCategory.FAMILY_OR_MECHANISM_TERM:
            return Decision(
                decision=CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
                reason="계열명/기전 용어는 수집 단위가 아니다",
            )
        blocked = self._blocked_category(row, category)
        if blocked is not None:
            return blocked
        if row.nia_case_count > 0 and row.confirmed_product_count == 0:
            # 제품이 없어도 성분·효능 정보 조회 use case 가 있어 버리지 않고, 이름·계보 확인 뒤 결정한다
            return Decision(
                decision=CollectionDecision.NAME_OR_LINEAGE_REVIEW,
                reason=f"NIA {row.nia_case_count}건이나 confirmed 제품 0개: 이름/계보 확인 후 결정",
                flags=flags,
            )
        if row.nia_case_count == 0 and row.confirmed_product_count < MIN_PRODUCTS_FOR_BASELINE:
            return Decision(
                decision=CollectionDecision.DEFER,
                reason=(
                    f"NIA 0건, 제품 {row.confirmed_product_count}개"
                    f"(<{MIN_PRODUCTS_FOR_BASELINE}) long tail"
                ),
                flags=flags,
            )
        if category in _PLANT_CATEGORIES and not self._plant_relevant(row):
            reason = (
                "safety-review 후보: 사람 검토 전 자동 수집 안 함"
                if flags
                else (
                    f"{category.value}: NIA 0·근거 0"
                    f"(제품 {row.confirmed_product_count}개만으로는 수집 안 함)"
                )
            )
            return Decision(decision=CollectionDecision.DEFER, reason=reason, flags=flags)
        if self._is_qa_priority(row, category):
            return Decision(
                decision=CollectionDecision.QA_PRIORITY,
                reason="수집 대상 + 사람 QA 우선(NIA/제품/routing 기준)",
                flags=flags,
            )
        return Decision(
            decision=CollectionDecision.COLLECT_BASELINE, reason="baseline 수집 대상", flags=flags
        )

    def _blocked_category(self, row: CoverageRow, category: UniverseCategory) -> Decision | None:
        if category in _FORMULATION_CATEGORIES:
            if _IRRITANT_SURFACTANT.search(row.ingredient_name):
                return Decision(
                    decision=CollectionDecision.DEFER,
                    reason="safety_relevant: 자극성 세정 계면활성제(안전성·장벽 근거 가치), 우선순위는 낮음",
                    flags=(ReviewFlag.SAFETY_RELEVANT,),
                )
            if row.nia_case_count > 0:
                return Decision(
                    decision=CollectionDecision.DEFER,
                    reason=f"{category.value}이나 NIA {row.nia_case_count}건 언급 - 사람 확인",
                )
            return Decision(
                decision=CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
                reason=f"{category.value}: 제형 기능이 주된 역할이라 효능·안전성 상담 근거 대상이 아님",
            )
        if category is UniverseCategory.BASE_SOLVENT_HUMECTANT:
            # 아미노산·당류·보습제는 barrier/safety 근거 가치가 있을 수 있어 EXCLUDE 하지 않고 보류한다
            return Decision(
                decision=CollectionDecision.DEFER,
                reason="base/humectant/amino acid: blanket 제외하지 않음, 독립 효능 우선순위 낮아 보류",
            )
        if category is UniverseCategory.FRAGRANCE_ALLERGEN:
            return Decision(
                decision=CollectionDecision.DEFER,
                reason="향료 알레르겐: 안전성 전용 근거로 별도 판단",
                flags=(ReviewFlag.SAFETY_RELEVANT,),
            )
        return None

    def _plant_relevant(self, row: CoverageRow) -> bool:
        return row.nia_case_count > 0 or row.scientific_document_count > 0

    def _is_qa_priority(self, row: CoverageRow, category: UniverseCategory) -> bool:
        if row.ingredient_name in SMOKE_INGREDIENTS:
            return True
        if row.priority_tier in (PriorityTier.P1, PriorityTier.P3):
            return True
        if row.nia_case_count >= QA_NIA_MIN_CASES:
            return True
        return (
            category is UniverseCategory.ACTIVE_OR_FUNCTIONAL
            and row.confirmed_product_count >= QA_ACTIVE_MIN_PRODUCTS
        )


class FamilyDetector:
    def families_of(self, name: str) -> list[str]:
        return [f.name for f in FAMILY_RULES if re.search(f.pattern, name, re.IGNORECASE)]

    def members(self, rows: list[CoverageRow]) -> list[FamilyMemberRow]:
        result: list[FamilyMemberRow] = []
        for family in FAMILY_RULES:
            pattern = re.compile(family.pattern, re.IGNORECASE)
            matched = [r for r in rows if pattern.search(r.ingredient_name)]
            matched.sort(key=lambda r: (-r.confirmed_product_count, r.ingredient_name))
            result.extend(
                FamilyMemberRow(
                    family=family.name,
                    ingredient_id=r.ingredient_id,
                    ingredient_name=r.ingredient_name,
                    nia_case_count=r.nia_case_count,
                    confirmed_product_count=r.confirmed_product_count,
                    scientific_document_count=r.scientific_document_count,
                )
                for r in matched
            )
        return result


class UniverseBuilder:
    def __init__(self, registry: SafetyReviewRegistry | None = None) -> None:
        self._eligibility = CollectionEligibility(registry)
        self._families = FamilyDetector()

    def build(self, rows: list[CoverageRow]) -> list[UniverseRow]:
        result: list[UniverseRow] = []
        for r in rows:
            category = self._eligibility.category(r.ingredient_name)
            decided = self._eligibility.decide(r, category)
            result.append(
                UniverseRow(
                    ingredient_id=r.ingredient_id,
                    ingredient_name=r.ingredient_name,
                    category=category,
                    decision=decided.decision,
                    decision_reason=decided.reason,
                    nia_case_count=r.nia_case_count,
                    confirmed_product_count=r.confirmed_product_count,
                    scientific_document_count=r.scientific_document_count,
                    current_priority_tier=r.priority_tier,
                    flags=";".join(f.value for f in decided.flags),
                    families=";".join(self._families.families_of(r.ingredient_name)),
                    in_smoke_set=r.ingredient_name in SMOKE_INGREDIENTS,
                )
            )
        return result

    def family_members(self, rows: list[CoverageRow]) -> list[FamilyMemberRow]:
        return self._families.members(rows)

    def summary(self, universe: list[UniverseRow]) -> str:
        by_decision = Counter(u.decision.value for u in universe)
        cross: dict[str, Counter[str]] = defaultdict(Counter)
        for u in universe:
            cross[u.category.value][u.decision.value] += 1
        lines = [f"universe={len(universe)} decisions={dict(by_decision)}"]
        lines += [f"  {cat}: {dict(c)}" for cat, c in sorted(cross.items())]
        return "\n".join(lines)


QA_SAMPLE_SEED = 20260921  # 같은 입력이면 같은 50개가 나오게 고정한다
QA_SAMPLE_PER_STRATUM = 10
_QA_ACTIVE = "collect_active"
_QA_BOTANICAL = "collect_botanical"


class StratifiedQaSampler:
    """규칙 보정 전 사람이 볼 50개: active 10 / botanical 10 / QA_PRIORITY 10 / DEFER 10 / EXCLUDE 10."""

    def sample(self, universe: list[UniverseRow]) -> list[tuple[str, UniverseRow]]:
        strata: dict[str, list[UniverseRow]] = {
            _QA_ACTIVE: [
                u
                for u in universe
                if u.decision is CollectionDecision.COLLECT_BASELINE
                and u.category is not UniverseCategory.BOTANICAL_OR_FERMENT
            ],
            _QA_BOTANICAL: [
                u
                for u in universe
                if u.decision is CollectionDecision.COLLECT_BASELINE
                and u.category is UniverseCategory.BOTANICAL_OR_FERMENT
            ],
            CollectionDecision.QA_PRIORITY.value: [
                u for u in universe if u.decision is CollectionDecision.QA_PRIORITY
            ],
            CollectionDecision.DEFER.value: [
                u for u in universe if u.decision is CollectionDecision.DEFER
            ],
            CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION.value: [
                u
                for u in universe
                if u.decision is CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION
            ],
        }
        rng = random.Random(QA_SAMPLE_SEED)
        picked: list[tuple[str, UniverseRow]] = []
        for label, members in strata.items():
            members = sorted(
                members, key=lambda u: str(u.ingredient_id)
            )  # 순서를 고정해야 seed 가 의미 있다
            picked.extend(
                (label, u) for u in rng.sample(members, min(QA_SAMPLE_PER_STRATUM, len(members)))
            )
        return picked


class CollectorInputExporter:
    """universe 결과를 기존 compact collector 입력(CollectionIngredient JSON)으로 내보낸다. 수동 목록을 따로 만들지 않는다."""

    @staticmethod
    def build_ingredient(
        ingredient_id: UUID, name_en: str, name_ko: str | None, old_names_en: list[str]
    ) -> CollectionIngredient:
        """aliases 에는 IngredientMaster 의 구 영문명(exact-equivalent)만 넣는다.

        family expansion 용어나 파생형은 원형 성분에 결과가 자동 귀속되므로 여기서 절대 넣지 않는다.
        """
        aliases: list[str] = []
        for name in old_names_en:
            if name and name != name_en and name not in aliases:
                aliases.append(name)
        return CollectionIngredient(
            ingredient_id=ingredient_id,
            standard_name_en=name_en,
            standard_name_ko=name_ko,
            aliases=aliases,
        )

    async def export(
        self,
        database_url: str,
        universe: list[UniverseRow],
        names: list[str],
        output_path: Path,
    ) -> list[CollectionIngredient]:
        by_name = {u.ingredient_name: u for u in universe}
        missing = [n for n in names if n not in by_name]
        if missing:
            raise ValueError(f"universe 에 없는 성분명: {missing}")
        ids = {by_name[n].ingredient_id: n for n in names}
        engine = create_async_engine(database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                await session.execute(text("SET TRANSACTION READ ONLY"))
                result = await session.execute(
                    select(
                        IngredientMaster.id,
                        IngredientMaster.standard_name_ko,
                        IngredientMaster.old_names_en,
                    ).where(IngredientMaster.id.in_(ids))
                )
                rows = {r[0]: (r[1], list(r[2] or [])) for r in result.all()}
        finally:
            await engine.dispose()
        ingredients = [self.build_ingredient(i, n, rows[i][0], rows[i][1]) for i, n in ids.items()]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                [i.model_dump(mode="json") for i in ingredients], ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        return ingredients


_REVIEWED_FILENAME = "collection_universe_qa_sample_reviewed.csv"
_COLLECT_DECISIONS = frozenset(
    {CollectionDecision.COLLECT_BASELINE, CollectionDecision.QA_PRIORITY}
)
_EXPECTED_BY_VERDICT: dict[str, CollectionDecision] = {
    "KEEP": CollectionDecision.COLLECT_BASELINE,
    "DEFER": CollectionDecision.DEFER,
    "EXCLUDE": CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
    "UNCERTAIN": CollectionDecision.NAME_OR_LINEAGE_REVIEW,
}


class QaReplay:
    """사람이 검수한 50개 verdict 에 현재 규칙을 다시 적용해 일치도와 오류 유형을 센다."""

    def evaluate(self, reviewed_csv: Path, universe: list[UniverseRow]) -> dict[str, object]:
        by_id = {u.ingredient_id: u for u in universe}
        with reviewed_csv.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        strict = binary = false_include = false_exclude = missed_keep = 0
        errors: list[str] = []
        for r in rows:
            verdict = r["reviewer_verdict"]
            new = by_id[UUID(r["ingredient_id"])].decision
            expected = _EXPECTED_BY_VERDICT[verdict]
            keep = verdict == "KEEP"
            if (new in _COLLECT_DECISIONS) if keep else (new is expected):
                strict += 1
            else:
                errors.append(f"{r['ingredient_name']}: {verdict} vs {new.value}")
            if (new in _COLLECT_DECISIONS) == keep:
                binary += 1
            if new in _COLLECT_DECISIONS and not keep:
                false_include += 1
            if new is CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION and keep:
                false_exclude += 1
            if keep and new not in _COLLECT_DECISIONS:
                missed_keep += 1
        return {
            "total": len(rows),
            "strict_agreement": strict,
            "collect_vs_not_agreement": binary,
            "false_include": false_include,
            "false_exclude(KEEP인데 EXCLUDE)": false_exclude,
            "missed_keep(KEEP인데 수집 안 됨)": missed_keep,
            "disagreements": errors,
        }


async def _run(
    database_url: str,
    nia_summary: Path,
    output_dir: Path,
    export_file: Path | None,
    names: list[str],
) -> None:
    snapshot = await CoverageAuditRunner().load(database_url, nia_summary)
    builder = UniverseBuilder(SafetyReviewRegistry.load(_SAFETY_REGISTRY_PATH))
    universe = builder.build(snapshot.rows)
    writer = CoverageCsvWriter()
    writer.write(output_dir / _UNIVERSE_FILENAME, universe, UniverseRow)
    writer.write(
        output_dir / _FAMILY_FILENAME, builder.family_members(snapshot.rows), FamilyMemberRow
    )
    print(builder.summary(universe))
    reviewed = output_dir / _REVIEWED_FILENAME
    if reviewed.exists():
        registry = SafetyReviewRegistry.load(_SAFETY_REGISTRY_PATH)
        rule_only = UniverseBuilder(registry.without_approvals()).build(snapshot.rows)
        print("QA replay(registry 승인 포함):", QaReplay().evaluate(reviewed, universe))
        print("QA replay(규칙 단독):", QaReplay().evaluate(reviewed, rule_only))
    sample = StratifiedQaSampler().sample(universe)
    with (output_dir / _QA_SAMPLE_FILENAME).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "stratum",
                "ingredient_id",
                "ingredient_name",
                "category",
                "decision",
                "nia_case_count",
                "confirmed_product_count",
                "decision_reason",
                "reviewer_verdict",
                "reviewer_note",
            ]
        )
        for label, u in sample:
            w.writerow(
                [
                    label,
                    u.ingredient_id,
                    u.ingredient_name,
                    u.category.value,
                    u.decision.value,
                    u.nia_case_count,
                    u.confirmed_product_count,
                    u.decision_reason,
                    "",
                    "",
                ]
            )
    if export_file is not None:
        exported = await CollectorInputExporter().export(database_url, universe, names, export_file)
        print(f"exported={len(exported)} -> {export_file}")
    present = {u.ingredient_name for u in universe}
    missing = [n for n in (*SMOKE_INGREDIENTS, *MANUAL_DECISIONS) if n not in present]
    print(f"names_not_in_universe={missing}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--nia-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=_OUTPUT_DIR)
    parser.add_argument("--export-ingredients-file", type=Path, default=None)
    parser.add_argument(
        "--names", default="", help="쉼표로 구분한 성분명(--export-ingredients-file 과 함께)"
    )
    args = parser.parse_args()
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    asyncio.run(
        _run(
            args.database_url,
            args.nia_summary,
            args.output_dir,
            args.export_ingredients_file,
            names,
        )
    )
