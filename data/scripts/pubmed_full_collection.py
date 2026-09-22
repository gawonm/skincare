"""PubMed full collection: provisional universe(COLLECT_BASELINE + QA_PRIORITY, botanical 제외) 전체에 검색을 돌려 파일로 저장한다.

읽기 전용(PubMed E-utilities 읽기 요청만). embedding·DB write 없음. 결과는 성분×PMID 행 JSONL 과 성분별 진행 기록으로
남기며, 중단 후 재실행하면 이미 처리한 성분은 건너뛴다(출력 파일이 곧 진행 상태).

사용법:
    uv run python -m data.scripts.pubmed_full_collection \
        --database-url postgresql+asyncpg://app:app@localhost:5432/skincare_v4_final
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

import httpx
from pydantic import BaseModel

from data.scripts.evidence_collection_universe import CollectorInputExporter
from data.scripts.evidence_coverage_schemas import CollectionDecision, UniverseCategory, UniverseRow
from data.scripts.pubmed_client import PubmedClient
from data.scripts.pubmed_smoke_runner import PubmedSmokeRunner

_OUTPUT_DIR = Path("data/outputs/evidence_coverage")
UNIVERSE_CSV = _OUTPUT_DIR / "collection_universe.csv"
RESULT_JSONL = _OUTPUT_DIR / "pubmed_full.jsonl"
PROGRESS_JSONL = _OUTPUT_DIR / "pubmed_full_progress.jsonl"
INGREDIENTS_JSON = _OUTPUT_DIR / "pubmed_full_ingredients.json"

_COLLECT_DECISIONS = frozenset(
    {CollectionDecision.COLLECT_BASELINE, CollectionDecision.QA_PRIORITY}
)
# botanical 은 INCI 명칭 검색이 0건이라 이번 full collection 에서 제외한다(query normalization 은 별도 pilot)
_EXCLUDED_CATEGORIES = frozenset({UniverseCategory.BOTANICAL_OR_FERMENT})


class ProgressRecord(BaseModel):
    """성분 하나를 처리한 결과 요약. 검색 결과가 0건이거나 실패한 성분도 여기에는 남는다."""

    ingredient: str
    ingredient_id: str
    category: str
    decision: str
    queries: list[str]
    fetched: int
    error: str | None = None


class FullCollectionPlan:
    def eligible(self, universe: list[UniverseRow]) -> tuple[list[UniverseRow], int]:
        """(수집 대상, 제외된 botanical 수). 대상은 이름순이 아니라 id 순으로 고정한다."""
        collectable = [u for u in universe if u.decision in _COLLECT_DECISIONS]
        botanical = [u for u in collectable if u.category in _EXCLUDED_CATEGORIES]
        targets = [u for u in collectable if u.category not in _EXCLUDED_CATEGORIES]
        return sorted(targets, key=lambda u: str(u.ingredient_id)), len(botanical)


def load_universe(path: Path) -> list[UniverseRow]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [UniverseRow.model_validate(row) for row in csv.DictReader(f)]


def _done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as f:
        return {json.loads(line)["ingredient_id"] for line in f if line.strip()}


async def _run(database_url: str) -> None:
    universe = load_universe(UNIVERSE_CSV)
    targets, botanical_excluded = FullCollectionPlan().eligible(universe)
    print(f"eligible={len(targets)} botanical_excluded={botanical_excluded}", flush=True)

    ingredients = await CollectorInputExporter().export(
        database_url, universe, [u.ingredient_name for u in targets], INGREDIENTS_JSON
    )
    by_name = {i.standard_name_en: i for i in ingredients}
    done = _done_ids(PROGRESS_JSONL)
    print(f"resume: already_done={len(done)}", flush=True)

    runner = PubmedSmokeRunner(PubmedClient())
    with (
        RESULT_JSONL.open("a", encoding="utf-8") as result_out,
        PROGRESS_JSONL.open("a", encoding="utf-8") as progress_out,
    ):
        for index, u in enumerate(targets, start=1):
            ingredient = by_name[u.ingredient_name]
            if str(ingredient.ingredient_id) in done:
                continue
            stratum = u.decision.value
            error: str | None = None
            rows: list[dict[str, object]] = []
            try:
                rows = runner.run_one(stratum, ingredient)
            except (ValueError, RuntimeError, httpx.HTTPError) as e:
                # 한 성분의 실패가 전체를 멈추지 않게 하되 숨기지 않는다: 진행 기록에 원인을 남기고 보고서에서 센다
                error = f"{type(e).__name__}: {e}"
            for row in rows:
                row["category"] = u.category.value
                result_out.write(json.dumps(row, ensure_ascii=False) + "\n")
            result_out.flush()
            progress = ProgressRecord(
                ingredient=ingredient.standard_name_en,
                ingredient_id=str(ingredient.ingredient_id),
                category=u.category.value,
                decision=u.decision.value,
                queries=runner.last_queries,
                fetched=len(rows),
                error=error,
            )
            progress_out.write(progress.model_dump_json() + "\n")
            progress_out.flush()
            if index % 20 == 0 or error:
                print(
                    f"[{index}/{len(targets)}] {u.ingredient_name[:40]} fetched={len(rows)} error={error}",
                    flush=True,
                )
    print(f"done requests={runner.request_count}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.database_url))
