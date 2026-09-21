"""전수 QA 를 통과한(KEEP) PubMed selected 로 최종 bundle 을 만들고, UNCERTAIN/EXCLUDE 는 별도 파일로 보존한다.

embedding·DB write 는 하지 않는다. PubMed 읽기 요청은 PMID 로 journal·정확한 발행일을 채우는 데만 쓴다(citation 품질용,
제목·초록은 저장본과 같은지 확인하고 다르면 실패한다).

사용법:
    uv run python -m data.scripts.pubmed_final_bundle
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from data.scripts.evidence_collector_schemas import EvidenceBundle, PubmedAssessment, PubmedRecord
from data.scripts.pubmed_client import PubmedClient, PubmedSource
from data.scripts.pubmed_evidence_mapper import PubmedEvidenceMapper
from data.scripts.pubmed_reevaluate import PubmedReevaluator

_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
REVIEWED_CSV = _OUTPUT_DIR / "pubmed_final_selected_qa_reviewed.csv"
BUNDLE_JSONL = _OUTPUT_DIR / "pubmed_final_bundle.jsonl"
DEFERRED_CSV = _OUTPUT_DIR / "pubmed_deferred_uncertain.csv"
EXCLUDED_CSV = _OUTPUT_DIR / "pubmed_excluded_by_qa.csv"

VERDICT_KEEP = "KEEP"
VERDICT_UNCERTAIN = "UNCERTAIN"
VERDICT_EXCLUDE = "EXCLUDE"
_FETCH_BATCH = 20


class FinalBundleBuilder:
    def __init__(self, source: PubmedSource | None = None) -> None:
        self._source = source or PubmedClient()
        self._mapper = PubmedEvidenceMapper()

    def read_reviewed(self, path: Path = REVIEWED_CSV) -> list[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        unknown = {r["reviewer_verdict"] for r in rows} - {
            VERDICT_KEEP,
            VERDICT_UNCERTAIN,
            VERDICT_EXCLUDE,
        }
        if unknown:
            raise ValueError(f"알 수 없는 reviewer_verdict: {unknown}")
        return rows

    def _fresh_records(self, pmids: list[str]) -> dict[str, PubmedRecord]:
        """journal·정확한 발행일 보강용. 저장본과 제목이 다르면 어긋난 레코드이므로 실패시킨다."""
        result: dict[str, PubmedRecord] = {}
        for start in range(0, len(pmids), _FETCH_BATCH):
            for record in self._source.fetch(pmids[start : start + _FETCH_BATCH]):
                result[record.pmid] = record
        return result

    def build(
        self,
        assessments: dict[tuple[str, str], PubmedAssessment],
        reviewed: list[dict[str, str]],
        names: dict[str, list[str]],
    ) -> list[EvidenceBundle]:
        keep = [r for r in reviewed if r["reviewer_verdict"] == VERDICT_KEEP]
        by_pmid: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in keep:
            by_pmid[row["pmid"]].append(row)
        fresh = self._fresh_records(sorted(by_pmid))
        retrieved_at = datetime.now(UTC)

        bundles: list[EvidenceBundle] = []
        for pmid, rows in sorted(by_pmid.items()):
            first = assessments[(rows[0]["ingredient_id"], pmid)]
            record = first.record
            if pmid in fresh:
                latest = fresh[pmid]
                if latest.title != record.title:
                    raise RuntimeError(f"PMID {pmid} 제목이 저장본과 다릅니다: {latest.title!r}")
                record = record.model_copy(
                    update={"journal": latest.journal, "publication_date": latest.publication_date}
                )
            # 같은 PMID 가 여러 성분에 걸리면 claim topic 은 성분별 평가의 합집합이 아니라 첫 평가를 쓴다(초록이 같다)
            assessment = first.model_copy(update={"record": record})
            ids = [UUID(r["ingredient_id"]) for r in rows]
            raw_names = sorted({n for r in rows for n in names[r["ingredient_id"]]})
            bundles.append(
                self._mapper.to_bundle(
                    assessment,
                    ingredient_ids=ids,
                    raw_ingredient_names=raw_names,
                    retrieved_at=retrieved_at,
                )
            )
        return bundles

    def write_bundle(self, bundles: list[EvidenceBundle], path: Path = BUNDLE_JSONL) -> None:
        with path.open("w", encoding="utf-8") as f:
            for bundle in bundles:
                f.write(bundle.model_dump_json() + "\n")

    def write_side_files(self, reviewed: list[dict[str, str]]) -> tuple[int, int]:
        """UNCERTAIN 은 deferred-review 로, EXCLUDE 는 제외 기록으로 보존한다(나중에 근거 부족 성분 보강 시 재검토용)."""
        for verdict, path in ((VERDICT_UNCERTAIN, DEFERRED_CSV), (VERDICT_EXCLUDE, EXCLUDED_CSV)):
            rows = [r for r in reviewed if r["reviewer_verdict"] == verdict]
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(reviewed[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        counts = [
            sum(1 for r in reviewed if r["reviewer_verdict"] == v)
            for v in (VERDICT_UNCERTAIN, VERDICT_EXCLUDE)
        ]
        return counts[0], counts[1]


def main() -> None:
    builder = FinalBundleBuilder()
    reevaluator = PubmedReevaluator()
    assessments, _ = reevaluator.evaluate()
    reviewed = builder.read_reviewed()
    ingredients = {
        ingredient_id: [ing.standard_name_en, *ing.aliases]
        for ingredient_id, ing in reevaluator.ingredients.items()
    }
    bundles = builder.build(assessments, reviewed, ingredients)
    builder.write_bundle(bundles)
    deferred, excluded = builder.write_side_files(reviewed)
    ingredient_ids = {i for b in bundles for i in b.document.ingredient_ids}
    links = sum(len(b.document.ingredient_ids) for b in bundles)
    print(
        json.dumps(
            {
                "final_documents(unique_pmids)": len(bundles),
                "final_chunks": sum(len(b.chunks) for b in bundles),
                "ingredient_document_links": links,
                "ingredients_covered": len(ingredient_ids),
                "deferred_uncertain_rows": deferred,
                "excluded_rows": excluded,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
