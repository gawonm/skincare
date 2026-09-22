"""CIR 보강 registry 후보 목록과, 공개된 CIR report 존재 여부 확인.

CIR 사이트를 검색·스크래핑하지 않는다(robots.txt 의 /search/ 금지 준수). CIR report 는 International Journal of Toxicology /
Journal of the American College of Toxicology 에도 게재되므로, 그 게재 기록을 PubMed 읽기 요청으로 찾아 "report 가 실제로 있는가,
그 report 가 이 성분을 다루는가(제목/초록에 성분명이 있는가)"만 확인한다. attachment id·PDF 는 여기서 얻지 않는다:
registry(`CirReportCandidate` JSON)에 넣으려면 사람이 CIR status 페이지에서 확인해야 한다.

사용법:
    uv run python -m data.scripts.cir_registry_candidates
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel

from data.scripts.evidence_collector_schemas import PubmedRecord
from data.scripts.pubmed_client import PubmedClient, PubmedSource

_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
MATRIX_CSV = _OUTPUT_DIR / "ingredient_scientific_evidence_coverage.csv"
UNIVERSE_CSV = _OUTPUT_DIR / "collection_universe.csv"
BUNDLE_JSONL = _OUTPUT_DIR / "pubmed_final_bundle.jsonl"
CANDIDATES_CSV = _OUTPUT_DIR / "cir_registry_candidates.csv"
LOOKUP_JSON = _OUTPUT_DIR / "cir_report_lookup.json"

# "서비스 가치 높음" 기준은 collection universe 의 QA 기준과 같은 값을 쓴다
HIGH_PRODUCTS = 100
HIGH_NIA = 170
P3_MIN_PRODUCTS = 20
# 안전성 근거가 "약하다"고 보는 PubMed KEEP 문서 수 상한(precaution topic 이 있는 문서)
WEAK_PRECAUTION_MAX_DOCS = 1
LOOKUP_RETMAX = 20

_COLLECT = frozenset({"COLLECT_BASELINE", "QA_PRIORITY"})
_CIR_JOURNALS = '"Int J Toxicol"[Journal] OR "J Am Coll Toxicol"[Journal]'
_CIR_TITLE = re.compile(r"safety assessment|final report|amended", re.IGNORECASE)
PRIORITY_1 = "P1"
PRIORITY_2 = "P2"
PRIORITY_3 = "P3"


class CirCandidate(BaseModel):
    ingredient_id: str
    ingredient: str
    priority: str
    priority_reason: str
    product_count: int
    nia_case_count: int
    pubmed_keep_count: int
    pubmed_precaution_docs: int
    missing_claim_topics: str
    decision: str
    category: str


class CirCandidateBuilder:
    def build(
        self,
        matrix: dict[str, dict[str, str]],
        universe: dict[str, dict[str, str]],
        bundles: list[dict[str, object]],
    ) -> list[CirCandidate]:
        keep: Counter[str] = Counter()
        precaution_docs: Counter[str] = Counter()
        topics: dict[str, set[str]] = defaultdict(set)
        for bundle in bundles:
            document = bundle["document"]
            for ingredient_id in document["ingredient_ids"]:  # type: ignore[index]
                keep[ingredient_id] += 1
                topics[ingredient_id] |= set(document["claim_topics"])  # type: ignore[index]
                if "precaution" in document["claim_topics"]:  # type: ignore[index]
                    precaution_docs[ingredient_id] += 1

        candidates: list[CirCandidate] = []
        for ingredient_id, row in universe.items():
            if row["decision"] not in _COLLECT:
                continue
            m = matrix[ingredient_id]
            if int(m["cir_document_count"]) > 0:
                continue  # 이미 DB 에 CIR report 가 있는 성분
            products, nia = int(m["confirmed_product_count"]), int(m["nia_case_count"])
            db_evidence = int(m["scientific_document_count"]) > 0
            kept = keep[ingredient_id]
            has_evidence = kept > 0 or db_evidence
            weak_safety = (
                precaution_docs[ingredient_id] + int(m["safety_count"]) <= WEAK_PRECAUTION_MAX_DOCS
            )
            high = products >= HIGH_PRODUCTS or nia >= HIGH_NIA or row["decision"] == "QA_PRIORITY"
            missing = [t for t in ("efficacy", "precaution") if t not in topics[ingredient_id]]
            if not has_evidence and high:
                priority, reason = (
                    PRIORITY_1,
                    "PubMed KEEP 0건 + 서비스 가치 높음(제품/NIA/QA_PRIORITY)",
                )
            elif has_evidence and high:
                priority, reason = (
                    PRIORITY_2,
                    "PubMed 효능 근거는 있으나 CIR(전문가 검토 안전성 평가)이 없는 핵심 성분: 안전성 근거 약함",
                )
            elif products >= P3_MIN_PRODUCTS and (not has_evidence or weak_safety):
                priority, reason = (
                    PRIORITY_3,
                    "그 외 보강 필요(제품 20개 이상, 근거 없음 또는 안전성 약함)",
                )
            else:
                continue
            candidates.append(
                CirCandidate(
                    ingredient_id=ingredient_id,
                    ingredient=row["ingredient_name"],
                    priority=priority,
                    priority_reason=reason,
                    product_count=products,
                    nia_case_count=nia,
                    pubmed_keep_count=kept,
                    pubmed_precaution_docs=precaution_docs[ingredient_id],
                    missing_claim_topics=";".join(missing),
                    decision=row["decision"],
                    category=row["category"],
                )
            )
        return sorted(candidates, key=lambda c: (c.priority, -c.product_count, c.ingredient))


class CirReportLookup(BaseModel):
    ingredient: str
    found: bool
    reports: list[dict[str, object]]


class CirPublishedReportFinder:
    """공개 게재 기록(PubMed)에서 CIR report 를 찾는다. 제목·초록에 성분명이 있을 때만 "이 성분을 다룸"으로 본다."""

    def __init__(self, source: PubmedSource | None = None) -> None:
        self._source = source or PubmedClient()

    def find(self, ingredient: str) -> CirReportLookup:
        term = ingredient.replace('"', "").strip()
        query = f'("{term}"[Title/Abstract]) AND ({_CIR_JOURNALS})'
        pmids = self._source.search(query, LOOKUP_RETMAX)
        records = self._source.fetch(pmids) if pmids else []
        # CIR report 제목은 "Safety Assessment of..."뿐 아니라 "Retinol and Retinyl Palmitate"처럼 성분명만 있는 것도 있어
        # 제목 형식은 거르지 않고, 두 저널에서 제목에 성분명이 있는 것을 강한 후보로 본다(초록만 일치하면 약한 후보).
        reports = [self._report(r, term) for r in records]
        matched = [
            r
            for r in reports
            if r["matched_in"]
            and (r["matched_in"] == "title" or _CIR_TITLE.search(str(r["title"])))
        ]
        return CirReportLookup(ingredient=ingredient, found=bool(matched), reports=matched)

    @staticmethod
    def _report(record: PubmedRecord, term: str) -> dict[str, object]:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        where = (
            "title"
            if pattern.search(record.title)
            else ("abstract" if pattern.search(record.abstract or "") else "")
        )
        return {
            "pmid": record.pmid,
            "title": record.title,
            "year": record.publication_date.year if record.publication_date else None,
            "journal": record.journal,
            "matched_in": where,
        }


def _read_csv(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row[key]: row for row in csv.DictReader(f)}


def main() -> None:
    candidates = CirCandidateBuilder().build(
        _read_csv(MATRIX_CSV, "ingredient_id"),
        _read_csv(UNIVERSE_CSV, "ingredient_id"),
        [
            json.loads(line)
            for line in BUNDLE_JSONL.read_text(encoding="utf-8").splitlines()
            if line
        ],
    )
    with CANDIDATES_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CirCandidate.model_fields))
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate.model_dump())
    print(Counter(c.priority for c in candidates))

    finder = CirPublishedReportFinder()
    lookups = [
        finder.find(c.ingredient) for c in candidates if c.priority in (PRIORITY_1, PRIORITY_2)
    ]
    LOOKUP_JSON.write_text(
        json.dumps([x.model_dump() for x in lookups], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"lookup={len(lookups)} found={sum(x.found for x in lookups)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
