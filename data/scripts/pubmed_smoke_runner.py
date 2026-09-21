"""PubMed 50-smoke: universe 에서 고정 seed 로 성분 50개를 뽑아 새 PubMed 검색을 돌리고 판단 근거를 전부 저장한다.

읽기 전용(PubMed E-utilities 읽기 요청만). embedding·DB write·DB 쓰기 없음. 결과는 성분×PMID 한 줄씩 JSONL 로 남겨
query, 초록, MeSH, publication type, 분류 결과, selected/candidate/rejected 이유를 나중에 재평가할 수 있게 한다.

사용법:
    uv run python -m data.scripts.pubmed_smoke_runner \
        --database-url postgresql+asyncpg://app:app@localhost:5432/skincare_v4_final
"""

import argparse
import asyncio
import csv
import json
import random
import sys
from pathlib import Path

from data.scripts.evidence_collection_universe import CollectorInputExporter
from data.scripts.evidence_collector_schemas import (
    CollectionIngredient,
    PubmedRecord,
    PubmedSelectionDisposition,
)
from data.scripts.evidence_coverage_schemas import CollectionDecision, UniverseCategory, UniverseRow
from data.scripts.pubmed_client import PubmedClient, PubmedSource
from data.scripts.pubmed_evidence_collector import PubmedEvidenceCollector
from data.scripts.pubmed_selection_policy import PubmedSelectionPolicy

SMOKE_SEED = 20260921
MAX_SELECTED_PER_INGREDIENT = 3
_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
_UNIVERSE_CSV = _OUTPUT_DIR / "collection_universe.csv"
_RESULT_JSONL = _OUTPUT_DIR / "pubmed_smoke50.jsonl"
_SAMPLE_CSV = _OUTPUT_DIR / "pubmed_smoke50_sample.csv"

# 앞서 돌린 smoke 10 (성분명은 universe 의 영문 표준명)
EXISTING_SMOKE: tuple[str, ...] = (
    "Niacinamide",
    "Retinol",
    "Salicylic Acid",
    "Ascorbic Acid",
    "3-O-Ethyl Ascorbic Acid",
    "Centella Asiatica Extract",
    "Sodium Hyaluronate",
    "Hexapeptide-2",
    "Collagen",
    "BHA",
)
STRATUM_EXISTING = "existing_smoke"
STRATUM_ACTIVE = "collect_active"
STRATUM_BOTANICAL = "collect_botanical"
STRATUM_UV = "collect_uv_filter"
STRATUM_QA = "qa_priority"
_TARGETS: dict[str, int] = {STRATUM_ACTIVE: 20, STRATUM_BOTANICAL: 8, STRATUM_UV: 5, STRATUM_QA: 7}


class SmokeSampler:
    """층별 고정 seed 무작위 추출. 사람이 보기 좋은 성분을 고르지 않는다."""

    def sample(
        self, universe: list[UniverseRow]
    ) -> tuple[list[tuple[str, UniverseRow]], list[str]]:
        by_name = {u.ingredient_name: u for u in universe}
        missing = [n for n in EXISTING_SMOKE if n not in by_name]
        if missing:
            raise ValueError(f"universe 에 없는 기존 smoke 성분: {missing}")
        taken = {n for n in EXISTING_SMOKE}
        picked: list[tuple[str, UniverseRow]] = [
            (STRATUM_EXISTING, by_name[n]) for n in EXISTING_SMOKE
        ]

        collect = CollectionDecision.COLLECT_BASELINE
        pools: dict[str, list[UniverseRow]] = {
            STRATUM_ACTIVE: [
                u
                for u in universe
                if u.decision is collect and u.category is UniverseCategory.ACTIVE_OR_FUNCTIONAL
            ],
            STRATUM_BOTANICAL: [
                u
                for u in universe
                if u.decision is collect and u.category is UniverseCategory.BOTANICAL_OR_FERMENT
            ],
            STRATUM_UV: [
                u
                for u in universe
                if u.decision is collect and u.category is UniverseCategory.UV_FILTER
            ],
            STRATUM_QA: [u for u in universe if u.decision is CollectionDecision.QA_PRIORITY],
        }
        notes: list[str] = []
        rng = random.Random(SMOKE_SEED)
        shortfall = 0
        for stratum in (STRATUM_UV, STRATUM_BOTANICAL, STRATUM_QA, STRATUM_ACTIVE):
            pool = sorted(
                (u for u in pools[stratum] if u.ingredient_name not in taken),
                key=lambda u: str(u.ingredient_id),  # 순서를 고정해야 seed 가 의미 있다
            )
            want = _TARGETS[stratum] + (shortfall if stratum == STRATUM_ACTIVE else 0)
            chosen = rng.sample(pool, min(want, len(pool)))
            if stratum != STRATUM_ACTIVE and len(chosen) < _TARGETS[stratum]:
                shortfall += _TARGETS[stratum] - len(chosen)
                notes.append(f"{stratum}: {len(chosen)}/{_TARGETS[stratum]} (active 에서 보충)")
            for u in chosen:
                taken.add(u.ingredient_name)
                picked.append((stratum, u))
        return picked, notes


class _RecordingSource:
    """PubmedSource 를 감싸 query 와 가져온 record 를 기록한다."""

    def __init__(self, inner: PubmedSource) -> None:
        self._inner = inner
        self.queries: list[str] = []
        self.records: dict[str, PubmedRecord] = {}

    @property
    def request_count(self) -> int:
        return getattr(self._inner, "request_count", 0)

    def search(self, query: str, retmax: int) -> list[str]:
        self.queries.append(query)
        return self._inner.search(query, retmax)

    def fetch(self, pmids: list[str]) -> list[PubmedRecord]:
        records = self._inner.fetch(pmids)
        for record in records:
            self.records.setdefault(record.pmid, record)
        return records

    def reset(self) -> None:
        self.queries = []
        self.records = {}


class PubmedSmokeRunner:
    def __init__(self, source: PubmedSource) -> None:
        self._source = _RecordingSource(source)
        self._policy = PubmedSelectionPolicy(MAX_SELECTED_PER_INGREDIENT)
        self._collector = PubmedEvidenceCollector(self._source, self._policy)

    @property
    def request_count(self) -> int:
        return self._source.request_count

    @property
    def last_queries(self) -> list[str]:
        """직전 run_one 이 보낸 query. 결과가 0건이어도 남는다."""
        return list(self._source.queries)

    def run_one(self, stratum: str, ingredient: CollectionIngredient) -> list[dict[str, object]]:
        """성분 하나의 결과를 성분×PMID 행으로 돌려준다. 버려진 record 도 사유와 함께 남긴다."""
        self._source.reset()
        result = self._collector.collect(ingredient)
        final = {a.record.pmid: a for a in result.assessments}
        rows: list[dict[str, object]] = []
        for pmid, record in self._source.records.items():
            assessment = final.get(pmid) or self._policy.assess_record(ingredient, record)
            in_result = pmid in final
            disposition = assessment.disposition
            rows.append(
                {
                    "stratum": stratum,
                    "ingredient": ingredient.standard_name_en,
                    "ingredient_id": str(ingredient.ingredient_id),
                    "aliases": ingredient.aliases,
                    "queries": self._source.queries,
                    "pmid": pmid,
                    "title": record.title,
                    "abstract": record.abstract,
                    "mesh_terms": record.mesh_terms,
                    "publication_types": record.publication_types,
                    "year": record.publication_date.year if record.publication_date else None,
                    "doi": record.doi,
                    "route": assessment.route.value,
                    "study_design": assessment.study_design.value,
                    "study_type": assessment.study_type.value,
                    "ingredient_role": assessment.ingredient_role.value,
                    "skin_relevance": assessment.skin_relevance.value,
                    "claim_topics": [t.value for t in assessment.claim_topics],
                    "formulation_type": assessment.formulation_type.value,
                    "evidence_grade": assessment.evidence_grade.value,
                    "disposition": disposition.value,
                    # 최종 결과에 못 든 candidate 는 상한(10) 때문에 잘린 것이다
                    "in_final_result": in_result,
                    "reason": assessment.reason.value if assessment.reason else None,
                }
            )
        return rows


def _load_universe(path: Path) -> list[UniverseRow]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [UniverseRow.model_validate(row) for row in csv.DictReader(f)]


async def _run(database_url: str) -> None:
    universe = _load_universe(_UNIVERSE_CSV)
    sample, notes = SmokeSampler().sample(universe)
    with _SAMPLE_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["stratum", "ingredient_id", "ingredient_name", "category", "decision"])
        for stratum, u in sample:
            writer.writerow(
                [stratum, u.ingredient_id, u.ingredient_name, u.category.value, u.decision.value]
            )
    print(f"sample={len(sample)} notes={notes}")

    names = [u.ingredient_name for _, u in sample]
    exporter_path = _OUTPUT_DIR / "pubmed_smoke50_ingredients.json"
    ingredients = await CollectorInputExporter().export(
        database_url, universe, names, exporter_path
    )
    by_name = {i.standard_name_en: i for i in ingredients}

    runner = PubmedSmokeRunner(PubmedClient())
    with _RESULT_JSONL.open("w", encoding="utf-8") as out:
        for stratum, u in sample:
            rows = runner.run_one(stratum, by_name[u.ingredient_name])
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            selected = sum(
                1
                for r in rows
                if r["disposition"] == PubmedSelectionDisposition.SELECTED.value
                and r["in_final_result"]
            )
            print(
                f"{stratum:18} {u.ingredient_name[:40]:40} fetched={len(rows):3} selected={selected}",
                flush=True,
            )
    print(f"requests={runner.request_count}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.database_url))
