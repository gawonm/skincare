"""PubMed full collection 결과의 자동 품질 리포트와 human QA 표본. 읽기 전용 후처리이며 외부 호출·DB 쓰기가 없다.

사용법:
    uv run python -m data.scripts.pubmed_collection_report
"""

import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel

from data.scripts.pubmed_full_collection import PROGRESS_JSONL, RESULT_JSONL, ProgressRecord

_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
SUMMARY_JSON = _OUTPUT_DIR / "pubmed_full_summary.json"
QA_SAMPLE_CSV = _OUTPUT_DIR / "pubmed_full_qa_sample.csv"

QA_SAMPLE_SEED = 20260921
QA_SAMPLE_TARGET = 50
# 우선순위 순서대로 한도까지 채운다. 마지막 남은 자리는 category 층화 무작위로 채운다.
_QA_SUSPICIOUS_CAP = 15
_QA_PRIORITY_DECISION_CAP = 10
_QA_COMBINATION_CAP = 8
_QA_REVIEW_CAP = 8

_GRADE_DIRECT = "direct_single_topical_human"
_GRADE_REVIEW = "topical_review"
_GRADE_COMBINATION = "combination_topical_human"
_QA_PRIORITY_DECISION = "QA_PRIORITY"

# 성분명 뒤에 붙으면 다른 물질(염·에스터)이 되는 접미어. 성분 본체가 아니라는 신호로만 쓴다.
_DERIVATIVE_SUFFIXES = frozenset(
    {
        "palmitate",
        "acetate",
        "phosphate",
        "glucoside",
        "sulfate",
        "ester",
        "esters",
        "propionate",
        "retinoate",
        "hydrochloride",
        "stearate",
        "chloride",
    }
)
_NUMBER_TOKEN = re.compile(r"^\d[\d.,]*%?$")
_PREVIOUS_TOKEN = re.compile(r"([A-Za-z0-9][A-Za-z0-9\-]*)[ \-]*$")
_NEXT_TOKEN = re.compile(r"^[ ]*([A-Za-z][A-Za-z0-9\-]*)")


class NameBoundaryChecker:
    """제목에서 성분명이 다른 물질명의 일부로 쓰였는지 의심한다. 자동 판정이 아니라 human QA 우선 표시용 휴리스틱이다."""

    def suspicious(self, title: str, names: list[str]) -> bool:
        for name in names:
            for match in re.finditer(
                rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", title, re.IGNORECASE
            ):
                if self._modified_before(title[: match.start()]) or self._modified_after(
                    title[match.end() :]
                ):
                    return True
        return False

    def _modified_before(self, before: str) -> bool:
        if before.endswith("-"):  # "para-hydroxycinnamic acid" 처럼 접두 결합
            return True
        token = _PREVIOUS_TOKEN.search(before)
        if token is None:
            return False
        word = token.group(1)
        if _NUMBER_TOKEN.match(word):  # "2% niacinamide" 의 농도 표기는 수식어가 아니다
            return False
        # "quaternium-18 bentonite" 처럼 숫자·하이픈이 든 화학 접두어
        return bool(re.search(r"\d", word)) or ("-" in word and word.lower() != "all-trans")

    def _modified_after(self, after: str) -> bool:
        token = _NEXT_TOKEN.match(after)
        return token is not None and token.group(1).lower() in _DERIVATIVE_SUFFIXES


class CategoryCounts(BaseModel):
    ingredients: int
    ingredients_with_selected: int
    candidates: int
    selected: int


class CollectionSummary(BaseModel):
    queried_ingredients: int
    errors: list[str]
    zero_result_ingredients: int
    records_fetched: int
    candidates: int
    selected: int
    ingredients_with_selected: int
    zero_selected_ingredients: int
    by_category: dict[str, CategoryCounts]
    by_decision: dict[str, CategoryCounts]
    by_grade: dict[str, int]
    risk_counts: dict[str, int]


class PubmedCollectionReporter:
    def __init__(self, results: Path = RESULT_JSONL, progress: Path = PROGRESS_JSONL) -> None:
        self._rows = [
            json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line
        ]
        self._progress = [
            ProgressRecord.model_validate_json(line)
            for line in progress.read_text(encoding="utf-8").splitlines()
            if line
        ]
        self._checker = NameBoundaryChecker()

    @staticmethod
    def _is_selected(row: dict[str, object]) -> bool:
        return row["disposition"] == "selected" and bool(row["in_final_result"])

    @staticmethod
    def _is_candidate(row: dict[str, object]) -> bool:
        return row["disposition"] == "candidate" and bool(row["in_final_result"])

    def _names(self, row: dict[str, object]) -> list[str]:
        aliases = row["aliases"]
        return (
            [str(row["ingredient"]), *(str(a) for a in aliases)]
            if isinstance(aliases, list)
            else [str(row["ingredient"])]
        )

    def is_suspicious(self, row: dict[str, object]) -> bool:
        return self._checker.suspicious(str(row["title"]), self._names(row))

    def selected_rows(self) -> list[dict[str, object]]:
        return [r for r in self._rows if self._is_selected(r)]

    def summarize(self) -> CollectionSummary:
        selected = self.selected_rows()
        candidates = [r for r in self._rows if self._is_candidate(r)]
        selected_ids = {r["ingredient_id"] for r in selected}
        return CollectionSummary(
            queried_ingredients=len(self._progress),
            errors=[f"{p.ingredient}: {p.error}" for p in self._progress if p.error],
            zero_result_ingredients=sum(
                1 for p in self._progress if p.fetched == 0 and not p.error
            ),
            records_fetched=len(self._rows),
            candidates=len(candidates),
            selected=len(selected),
            ingredients_with_selected=len(selected_ids),
            zero_selected_ingredients=len(self._progress) - len(selected_ids),
            by_category=self._group(lambda p: p.category, lambda r: str(r["category"])),
            by_decision=self._group(lambda p: p.decision, lambda r: str(r["stratum"])),
            by_grade=dict(Counter(str(r["evidence_grade"]) for r in selected)),
            risk_counts=self._risk_counts(selected, candidates),
        )

    def _group(self, progress_key, row_key) -> dict[str, CategoryCounts]:
        ingredients: dict[str, int] = Counter(progress_key(p) for p in self._progress)
        selected_by: dict[str, list[dict[str, object]]] = defaultdict(list)
        candidates_by: Counter[str] = Counter()
        for row in self._rows:
            if self._is_selected(row):
                selected_by[row_key(row)].append(row)
            elif self._is_candidate(row):
                candidates_by[row_key(row)] += 1
        return {
            key: CategoryCounts(
                ingredients=count,
                ingredients_with_selected=len({r["ingredient_id"] for r in selected_by[key]}),
                candidates=candidates_by[key],
                selected=len(selected_by[key]),
            )
            for key, count in sorted(ingredients.items())
        }

    def _risk_counts(
        self, selected: list[dict[str, object]], candidates: list[dict[str, object]]
    ) -> dict[str, int]:
        reasons = Counter(str(r["reason"]) for r in candidates)
        return {
            "selected_derivative_or_name_boundary_suspicious": sum(
                self.is_suspicious(r) for r in selected
            ),
            "selected_combination": sum(
                r["evidence_grade"] == _GRADE_COMBINATION
                or r["formulation_type"] == "combination_formulation"
                for r in selected
            ),
            "selected_review": sum(r["evidence_grade"] == _GRADE_REVIEW for r in selected),
            "candidate_route_unclear": reasons["route_unclear"],
            "candidate_mixed_design_review": reasons["mixed_design_review"],
            "candidate_no_claim_topic": reasons["no_claim_topic"],
            "zero_result_queries": sum(1 for p in self._progress if p.fetched == 0 and not p.error),
        }

    def qa_sample(self) -> list[dict[str, object]]:
        """selected 층화 표본. 의심(파생/이름 경계) → QA_PRIORITY → 복합 → 리뷰 순으로 먼저 담고 나머지는 category 층화로 채운다."""
        rng = random.Random(QA_SAMPLE_SEED)
        selected = sorted(
            self.selected_rows(), key=lambda r: (str(r["ingredient_id"]), str(r["pmid"]))
        )
        picked: dict[tuple[str, str], tuple[str, dict[str, object]]] = {}

        def take(label: str, pool: list[dict[str, object]], cap: int) -> None:
            fresh = [r for r in pool if (str(r["ingredient_id"]), str(r["pmid"])) not in picked]
            for row in rng.sample(fresh, min(cap, len(fresh))):
                picked[(str(row["ingredient_id"]), str(row["pmid"]))] = (label, row)

        take(
            "name_boundary_suspicious",
            [r for r in selected if self.is_suspicious(r)],
            _QA_SUSPICIOUS_CAP,
        )
        take(
            "qa_priority",
            [r for r in selected if r["stratum"] == _QA_PRIORITY_DECISION],
            _QA_PRIORITY_DECISION_CAP,
        )
        take(
            "combination",
            [r for r in selected if r["evidence_grade"] == _GRADE_COMBINATION],
            _QA_COMBINATION_CAP,
        )
        take(
            "review", [r for r in selected if r["evidence_grade"] == _GRADE_REVIEW], _QA_REVIEW_CAP
        )

        by_category: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in selected:
            if (str(row["ingredient_id"]), str(row["pmid"])) not in picked:
                by_category[str(row["category"])].append(row)
        categories = sorted(by_category)
        while len(picked) < QA_SAMPLE_TARGET and any(by_category.values()):
            for category in categories:
                if len(picked) >= QA_SAMPLE_TARGET or not by_category[category]:
                    continue
                row = by_category[category].pop(rng.randrange(len(by_category[category])))
                picked[(str(row["ingredient_id"]), str(row["pmid"]))] = (
                    f"stratified:{category}",
                    row,
                )
        return [{**row, "qa_reason": label} for label, row in picked.values()]

    def write_outputs(
        self, summary_path: Path = SUMMARY_JSON, sample_path: Path = QA_SAMPLE_CSV
    ) -> None:
        summary_path.write_text(self.summarize().model_dump_json(indent=1), encoding="utf-8")
        sample = self.qa_sample()
        columns = [
            "qa_reason",
            "ingredient",
            "stratum",
            "category",
            "pmid",
            "title",
            "route",
            "study_design",
            "ingredient_role",
            "skin_relevance",
            "claim_topics",
            "formulation_type",
            "evidence_grade",
            "publication_types",
            "year",
            "reviewer_verdict",
            "reviewer_note",
        ]
        with sample_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in sample:
                writer.writerow(
                    {
                        **row,
                        "claim_topics": ";".join(row["claim_topics"]),
                        "publication_types": ";".join(row["publication_types"]),
                    }
                )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    reporter = PubmedCollectionReporter()
    reporter.write_outputs()
    print(reporter.summarize().model_dump_json(indent=1))
