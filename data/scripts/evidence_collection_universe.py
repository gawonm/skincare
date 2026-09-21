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
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from data.scripts.evidence_coverage_audit import CoverageAuditRunner, CoverageCsvWriter
from data.scripts.evidence_coverage_schemas import (
    CollectionDecision,
    CoverageRow,
    FamilyMemberRow,
    PriorityTier,
    UniverseCategory,
    UniverseRow,
)

# 제품 근거가 이 수 이상이거나 NIA 언급이 있어야 baseline 수집 대상으로 본다. 제품 1~4개짜리 long tail 은
# 수집해도 상담에서 쓰일 일이 드물어 DEFER 한다(임의 기준이며 사람 확인이 필요하다).
MIN_PRODUCTS_FOR_BASELINE = 5
QA_NIA_MIN_CASES = 170  # coverage audit 의 NIA 높음 기준과 같은 값
QA_ACTIVE_MIN_PRODUCTS = 100  # coverage audit 의 제품 높음 기준과 같은 값

_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
_UNIVERSE_FILENAME = "collection_universe.csv"
_FAMILY_FILENAME = "ingredient_family_candidates.csv"


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
        UniverseCategory.PEPTIDE_OR_PROTEIN,
        _rx(
            r"peptide", r"collagen", r"elastin", r"protein", r"keratin", r"albumen", r"^sodium dna$"
        ),
    ),
    (UniverseCategory.ACTIVE_OR_FUNCTIONAL, _rx(r"hyaluron")),
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
            r"^alcohol",
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

# 수집 자격이 없다고 보는 범주. 이 범주는 NIA 언급이 있어도 DEFER 로만 남기고 자동 수집하지 않는다.
_NON_ACTIVE_CATEGORIES = frozenset(
    {
        UniverseCategory.BASE_SOLVENT_HUMECTANT,
        UniverseCategory.PRESERVATIVE_STABILIZER,
        UniverseCategory.POLYMER_THICKENER,
        UniverseCategory.SURFACTANT_EMULSIFIER_EMOLLIENT,
        UniverseCategory.PH_ADJUSTER_SALT,
    }
)


class CollectionEligibility:
    """카테고리와 수집 자격을 규칙으로 정한다. 같은 입력이면 같은 결과가 나온다."""

    def category(self, name: str) -> UniverseCategory:
        for category, pattern in _CATEGORY_RULES:
            if pattern.search(name):
                return category
        return UniverseCategory.ACTIVE_OR_FUNCTIONAL

    def decide(
        self, row: CoverageRow, category: UniverseCategory
    ) -> tuple[CollectionDecision, str]:
        manual = MANUAL_DECISIONS.get(row.ingredient_name)
        if manual is not None:
            return manual
        if category is UniverseCategory.FAMILY_OR_MECHANISM_TERM:
            return (
                CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
                "계열명/기전 용어는 수집 단위가 아니다",
            )
        if category in _NON_ACTIVE_CATEGORIES:
            if row.nia_case_count > 0:
                return (
                    CollectionDecision.DEFER,
                    f"{category.value}이나 NIA {row.nia_case_count}건 언급 - 사람 확인",
                )
            return (
                CollectionDecision.EXCLUDE_FROM_SCIENTIFIC_COLLECTION,
                f"{category.value}: 제품에 들어가지만 효능·안전성 상담 근거 대상이 아님",
            )
        if category is UniverseCategory.FRAGRANCE_ALLERGEN:
            return CollectionDecision.DEFER, "향료 알레르겐: 안전성 전용 근거로 별도 판단"
        if row.nia_case_count == 0 and row.confirmed_product_count < MIN_PRODUCTS_FOR_BASELINE:
            return (
                CollectionDecision.DEFER,
                f"NIA 0건, 제품 {row.confirmed_product_count}개(<{MIN_PRODUCTS_FOR_BASELINE}) long tail",
            )
        if self._is_qa_priority(row, category):
            return CollectionDecision.QA_PRIORITY, "수집 대상 + 사람 QA 우선(NIA/제품/routing 기준)"
        return CollectionDecision.COLLECT_BASELINE, "baseline 수집 대상"

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
    def __init__(self) -> None:
        self._eligibility = CollectionEligibility()
        self._families = FamilyDetector()

    def build(self, rows: list[CoverageRow]) -> list[UniverseRow]:
        result: list[UniverseRow] = []
        for r in rows:
            category = self._eligibility.category(r.ingredient_name)
            decision, reason = self._eligibility.decide(r, category)
            result.append(
                UniverseRow(
                    ingredient_id=r.ingredient_id,
                    ingredient_name=r.ingredient_name,
                    category=category,
                    decision=decision,
                    decision_reason=reason,
                    nia_case_count=r.nia_case_count,
                    confirmed_product_count=r.confirmed_product_count,
                    scientific_document_count=r.scientific_document_count,
                    current_priority_tier=r.priority_tier,
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


async def _run(database_url: str, nia_summary: Path, output_dir: Path) -> None:
    snapshot = await CoverageAuditRunner().load(database_url, nia_summary)
    builder = UniverseBuilder()
    universe = builder.build(snapshot.rows)
    writer = CoverageCsvWriter()
    writer.write(output_dir / _UNIVERSE_FILENAME, universe, UniverseRow)
    writer.write(
        output_dir / _FAMILY_FILENAME, builder.family_members(snapshot.rows), FamilyMemberRow
    )
    print(builder.summary(universe))
    present = {u.ingredient_name for u in universe}
    missing = [n for n in (*SMOKE_INGREDIENTS, *MANUAL_DECISIONS) if n not in present]
    print(f"names_not_in_universe={missing}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--nia-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=_OUTPUT_DIR)
    args = parser.parse_args()
    asyncio.run(_run(args.database_url, args.nia_summary, args.output_dir))
