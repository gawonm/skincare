"""저장된 PubMed record(pubmed_full.jsonl)를 새 PubMed 호출 없이 현재 정책으로 다시 평가하고 이전 결과와 비교한다.

사용법:
    uv run python -m data.scripts.pubmed_reevaluate
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from data.scripts.evidence_collector_schemas import (
    CollectionIngredient,
    PubmedAssessment,
    PubmedRecord,
    PubmedSelectionDisposition,
)
from data.scripts.pubmed_full_collection import INGREDIENTS_JSON, RESULT_JSONL
from data.scripts.pubmed_selection_policy import PubmedSelectionPolicy

MAX_SELECTED = 3
QA_CSV = Path("data/outputs/evidence_coverage/pubmed_final_selected_qa.csv")
# 전수 QA 시트: 앞 9개가 검수 기준 컬럼이고, 뒤는 초록 대조용 참고 컬럼이다
_QA_COLUMNS = (
    "ingredient",
    "pmid",
    "title",
    "selection_grade",
    "route",
    "study_type",
    "claim_topics",
    "reviewer_verdict",
    "reviewer_reason",
    "abstract",
    "formulation_type",
    "publication_types",
    "year",
    "doi",
    "category",
    "stratum",
    "ingredient_id",
)


class SelectionChange(BaseModel):
    ingredient: str
    pmid: str
    title: str
    before_design: str
    after_design: str
    after_disposition: str
    after_reason: str | None


class ReevaluationResult(BaseModel):
    records: int
    selected_before: int
    selected_after: int
    removed: list[SelectionChange]
    newly_selected: list[SelectionChange]


class PubmedReevaluator:
    def __init__(self, results: Path = RESULT_JSONL, ingredients: Path = INGREDIENTS_JSON) -> None:
        self._rows = [
            json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line
        ]
        self._ingredients = {
            str(i.ingredient_id): i
            for i in (
                CollectionIngredient.model_validate(x)
                for x in json.loads(ingredients.read_text(encoding="utf-8"))
            )
        }
        self._policy = PubmedSelectionPolicy(MAX_SELECTED)

    @staticmethod
    def _record(row: dict[str, object]) -> PubmedRecord:
        year = row["year"]
        return PubmedRecord(
            pmid=str(row["pmid"]),
            doi=row["doi"] if isinstance(row["doi"], str) else None,
            title=str(row["title"]),
            abstract=row["abstract"] if isinstance(row["abstract"], str) else None,
            journal=None,
            publication_date=date(int(year), 1, 1) if isinstance(year, int) else None,
            publication_types=list(row["publication_types"]),  # type: ignore[arg-type]
            mesh_terms=list(row["mesh_terms"]),  # type: ignore[arg-type]
            authors=[],
        )

    def evaluate(self) -> tuple[dict[tuple[str, str], PubmedAssessment], ReevaluationResult]:
        by_ingredient: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in self._rows:
            by_ingredient[str(row["ingredient_id"])].append(row)

        after: dict[tuple[str, str], PubmedAssessment] = {}
        for ingredient_id, rows in by_ingredient.items():
            ingredient = self._ingredients[ingredient_id]
            for assessment in self._policy.assess(ingredient, [self._record(r) for r in rows]):
                after[(ingredient_id, assessment.record.pmid)] = assessment

        selected_after = {
            key for key, a in after.items() if a.disposition is PubmedSelectionDisposition.SELECTED
        }
        before_rows = {
            (str(r["ingredient_id"]), str(r["pmid"])): r
            for r in self._rows
            if r["disposition"] == "selected" and r["in_final_result"]
        }
        removed = [
            self._change(before_rows[key], after.get(key))
            for key in sorted(set(before_rows) - selected_after)
        ]
        row_by_key = {(str(r["ingredient_id"]), str(r["pmid"])): r for r in self._rows}
        newly = [
            self._change(row_by_key[key], after[key])
            for key in sorted(selected_after - set(before_rows))
        ]
        result = ReevaluationResult(
            records=len(self._rows),
            selected_before=len(before_rows),
            selected_after=len(selected_after),
            removed=removed,
            newly_selected=newly,
        )
        return after, result

    def write_qa_csv(
        self, after: dict[tuple[str, str], PubmedAssessment], path: Path = QA_CSV
    ) -> int:
        """재평가 후 최종 selected 전수를 QA 시트로 쓴다(reviewer_verdict 는 KEEP/EXCLUDE/UNCERTAIN, 비워 둔다)."""
        row_by_key = {(str(r["ingredient_id"]), str(r["pmid"])): r for r in self._rows}
        selected = sorted(
            (
                (key, a)
                for key, a in after.items()
                if a.disposition is PubmedSelectionDisposition.SELECTED
            ),
            key=lambda item: (str(row_by_key[item[0]]["ingredient"]).lower(), item[1].record.pmid),
        )
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(_QA_COLUMNS))
            writer.writeheader()
            for key, a in selected:
                row = row_by_key[key]
                writer.writerow(
                    {
                        "ingredient": row["ingredient"],
                        "pmid": a.record.pmid,
                        "title": a.record.title,
                        "selection_grade": a.evidence_grade.value,
                        "route": a.route.value,
                        "study_type": a.study_type.value,
                        "claim_topics": ";".join(t.value for t in a.claim_topics),
                        "reviewer_verdict": "",
                        "reviewer_reason": "",
                        "abstract": a.record.abstract,
                        "formulation_type": a.formulation_type.value,
                        "publication_types": ";".join(a.record.publication_types),
                        "year": row["year"],
                        "doi": a.record.doi,
                        "category": row.get("category"),
                        "stratum": row["stratum"],
                        "ingredient_id": row["ingredient_id"],
                    }
                )
        return len(selected)

    @staticmethod
    def _change(row: dict[str, object], after: PubmedAssessment | None) -> SelectionChange:
        return SelectionChange(
            ingredient=str(row["ingredient"]),
            pmid=str(row["pmid"]),
            title=str(row["title"]),
            before_design=str(row["study_design"]),
            after_design=after.study_design.value if after else "dropped",
            after_disposition=after.disposition.value if after else "dropped",
            after_reason=after.reason.value if after and after.reason else None,
        )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    reevaluator = PubmedReevaluator()
    assessments, outcome = reevaluator.evaluate()
    print(outcome.model_dump_json(indent=1))
    print(f"qa_rows={reevaluator.write_qa_csv(assessments)} -> {QA_CSV}")
