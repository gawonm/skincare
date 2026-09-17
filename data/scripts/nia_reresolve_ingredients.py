"""이미 LLM으로 라벨링된 `nia_10s_30s_annotations.jsonl`의 성분 매칭만 최신
`NiaIngredientMatchingStage`로 다시 계산해 덮어쓴다. LLM을 다시 부르지 않는다 —
저장된 `raw_name`/`raw_name_ko`를 그대로 재사용하는 순수 deterministic 재처리다.

`review_queue.jsonl`(ingredient unresolved 사유 갱신)과
`nia_10s_30s_claim_ingestion.jsonl`(ingestion 정책 재적용)도 같이 갱신한다.

사용법:
    uv run python -m data.scripts.nia_reresolve_ingredients
"""

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from core.config import settings
from core.database import Database
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.nia_claim_ingestion_policy import NiaClaimIngestionPolicy
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_llm_label_schemas import LlmIngredientMention

_ANNOTATIONS_PATH = Path("data/processed/nia_10s_30s_annotations.jsonl")
_REVIEW_QUEUE_PATH = Path("data/processed/nia_10s_30s_review_queue.jsonl")
_CLAIM_INGESTION_PATH = Path("data/processed/nia_10s_30s_claim_ingestion.jsonl")


def _re_resolve_subject(stage: NiaIngredientMatchingStage, subject: dict) -> dict:
    ambiguous = subject["matching_status"] == "unresolved_ambiguous_family"
    mention = LlmIngredientMention(
        raw_name=subject["raw_name"],
        raw_name_ko=subject.get("raw_name_ko"),
        ambiguous_family=ambiguous,
    )
    return stage.resolve(mention)


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


async def _run() -> None:
    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            candidates = await IngredientMasterRepository(session).list_all_as_candidates()
    finally:
        await database.dispose()
    matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
    stage = NiaIngredientMatchingStage(matcher)

    before = Counter()
    after = Counter()
    newly_matched: list[dict] = []

    docs = _read_jsonl(_ANNOTATIONS_PATH)

    for doc in docs:
        for s in doc["statements"]:
            if s["statement_type"] == "ingredient_effect_claim":
                before[s["subject"]["matching_status"]] += 1
                new_subject = _re_resolve_subject(stage, s["subject"])
                after[new_subject["matching_status"]] += 1
                if (
                    s["subject"]["matching_status"] != "matched"
                    and new_subject["matching_status"] == "matched"
                ):
                    newly_matched.append(
                        {
                            "record_id": doc["source"]["record_id"],
                            "statement_id": s["statement_id"],
                            "raw_name": s["subject"]["raw_name"],
                            "old_status": s["subject"]["matching_status"],
                            "new_ingredient_id": new_subject["ingredient_id"],
                        }
                    )
                s["subject"] = new_subject
            elif s["statement_type"] == "combination_claim":
                new_subjects = []
                for sub in s["subjects"]:
                    before[sub["matching_status"]] += 1
                    new_sub = _re_resolve_subject(stage, sub)
                    after[new_sub["matching_status"]] += 1
                    if (
                        sub["matching_status"] != "matched"
                        and new_sub["matching_status"] == "matched"
                    ):
                        newly_matched.append(
                            {
                                "record_id": doc["source"]["record_id"],
                                "statement_id": s["statement_id"],
                                "raw_name": sub["raw_name"],
                                "old_status": sub["matching_status"],
                                "new_ingredient_id": new_sub["ingredient_id"],
                            }
                        )
                    new_subjects.append(new_sub)
                s["subjects"] = new_subjects

    _write_jsonl(_ANNOTATIONS_PATH, docs)

    # review_queue의 "ingredient {status} (...)" 사유만 새 상태로 다시 만든다.
    # span/parser/reference 관련 사유는 성분 매칭과 무관하므로 그대로 둔다.
    policy = NiaClaimIngestionPolicy()
    review_queue = []
    claim_ingestion = []
    old_review_by_record = {}
    if _REVIEW_QUEUE_PATH.exists():
        for r in _read_jsonl(_REVIEW_QUEUE_PATH):
            old_review_by_record[r["record_id"]] = r["reasons"]

    for doc in docs:
        rid = doc["source"]["record_id"]
        old_reasons = old_review_by_record.get(rid, [])
        kept_reasons = [r for r in old_reasons if ": ingredient " not in r]
        new_ingredient_reasons = []
        for s in doc["statements"]:
            subs = []
            if s["statement_type"] == "ingredient_effect_claim":
                subs = [s["subject"]]
            elif s["statement_type"] == "combination_claim":
                subs = s["subjects"]
                if s["subject_plural_mode"] == "uncertain":
                    pass  # 기존 "combination_claim uncertain" 사유는 kept_reasons에 이미 보존됨
            for sub in subs:
                if sub["matching_status"] != "matched":
                    new_ingredient_reasons.append(
                        f"{s['statement_id']}: ingredient {sub['matching_status']} ({sub['raw_name']})"
                    )

            stmt_reasons = [r for r in old_reasons if r.startswith(s["statement_id"] + ":")]
            has_fuzzy_span = any("span fuzzy" in r for r in stmt_reasons)
            has_mismatch = any("span_semantic_mismatch" in r for r in stmt_reasons)
            has_low_conf = any("span_semantic_confidence_low" in r for r in stmt_reasons)
            semantic_verdict = (
                "mismatch" if has_mismatch else ("low_confidence" if has_low_conf else "ok")
            )
            decision = policy.decide(
                s, semantic_verdict=semantic_verdict, has_low_confidence_span=has_fuzzy_span
            )
            claim_ingestion.append(
                {
                    "record_id": rid,
                    "statement_id": s["statement_id"],
                    "statement_type": s["statement_type"],
                    "decision": decision.value,
                    "priority": policy.priority(s).value,
                }
            )

        all_reasons = kept_reasons + new_ingredient_reasons
        if all_reasons:
            review_queue.append({"record_id": rid, "reasons": all_reasons})

    _write_jsonl(_REVIEW_QUEUE_PATH, review_queue)
    _write_jsonl(_CLAIM_INGESTION_PATH, claim_ingestion)

    print("Before:", dict(before))
    print("After:", dict(after))
    print(f"새로 matched된 statement 수: {len(newly_matched)}")
    for item in newly_matched[:10]:
        print(" ", item)
    print(f"저장: {_ANNOTATIONS_PATH}, {_REVIEW_QUEUE_PATH}, {_CLAIM_INGESTION_PATH}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run())
