"""`nia_qa_10s_30s.jsonl`에서 30~50건 stratified pilot을 뽑아 LLM 의미 라벨링 →
ingredient deterministic 매칭 → `NiaLabelingParser` 검증까지 실행한다.

전체 3,581건은 이번 실행 범위가 아니다. 이 스크립트는 pilot 규모로 pipeline
correctness를 먼저 검증하기 위한 것이다.

사용법:
    uv run python -m data.scripts.nia_pilot_runner
"""

import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from core.config import settings
from core.database import Database
from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_llm_label_schemas import LlmNiaLabelingOutput
from data.scripts.nia_llm_labeler import NiaLlmLabeler
from data.scripts.nia_record_provenance import NiaRecordProvenanceIndex
from data.scripts.nia_source_span_builder import NiaSourceSpanBuildError, NiaSourceSpanBuilder

sys.path.insert(0, str(Path("data/manual_review")))
from nia_labeling_parser import KNOWN_PLACEHOLDER_PATTERNS, NiaLabelingParser  # noqa: E402

_RECORDS_PATH = Path("data/processed/nia_qa_10s_30s.jsonl")
_PILOT_SIZE = 40
_SCHEMA_VERSION = "1.1"
_ANNOTATION_VERSION = "llm-pilot-2026-09-14"

_ANNOTATIONS_PATH = Path("data/processed/nia_10s_30s_annotations.jsonl")
_FAILURES_PATH = Path("data/processed/nia_10s_30s_labeling_failures.jsonl")
_REVIEW_QUEUE_PATH = Path("data/processed/nia_10s_30s_review_queue.jsonl")
_CHECKPOINT_PATH = Path("data/processed/.nia_10s_30s_pilot_checkpoint.txt")
_RAW_RECORDS_COMPANION_PATH = Path("data/processed/.nia_10s_30s_pilot_raw_records.json")

_AGE_TEXT_RE = re.compile(r"\d+세")


class NiaPilotSampler:
    """구조 감사(risk_level/flag) 분포를 따라 edge case를 포함하는 pilot 표본을 뽑는다."""

    def __init__(self, provenance: NiaRecordProvenanceIndex) -> None:
        self._provenance = provenance

    def sample(self, records: dict[str, dict], size: int) -> list[str]:
        by_risk: dict[str, list[str]] = defaultdict(list)
        for record_id in records:
            prov = self._provenance.get(record_id)
            if prov is None:
                continue
            by_risk[prov.risk_level].append(record_id)
        for ids in by_risk.values():
            ids.sort()

        picked: list[str] = []
        risk_levels = [lvl for lvl in ("HIGH", "MEDIUM", "LOW") if by_risk.get(lvl)]
        per_level = max(1, size // max(1, len(risk_levels)))
        for level in risk_levels:
            picked.extend(by_risk[level][:per_level])
        return picked[:size]


class NiaPilotRecordProcessor:
    def __init__(
        self,
        labeler: NiaLlmLabeler,
        span_builder: NiaSourceSpanBuilder,
        matching_stage: NiaIngredientMatchingStage,
        provenance: NiaRecordProvenanceIndex,
    ) -> None:
        self._labeler = labeler
        self._span_builder = span_builder
        self._matching_stage = matching_stage
        self._provenance = provenance

    async def process(self, record_id: str, record: dict) -> dict:
        """LLM 라벨링 + deterministic 후처리를 거쳐 `NiaLabelingDocument` 형태의 raw dict를 만든다.
        실패(quote 원문 불일치 등)는 예외로 전파해 호출부가 failures로 분류한다."""
        llm_output = await self._labeler.label(record)
        statements = self._build_statements(record_id, record, llm_output)
        return {
            "schema_version": _SCHEMA_VERSION,
            "annotation_version": _ANNOTATION_VERSION,
            "is_example": False,
            "is_partial_annotation": True,
            "production_ready": False,
            "annotator_count": 1,
            "source": self._build_source(record_id, record),
            "case_context": self._build_case_context(record),
            "statements": statements,
            "references": self._build_references(record),
            "notes": ["LLM 자동 라벨링 결과, 사람 검토 전(pending_review)."],
        }

    def _build_statements(
        self, record_id: str, record: dict, llm_output: LlmNiaLabelingOutput
    ) -> list[dict]:
        statements = []
        for idx, stmt in enumerate(llm_output.statements, start=1):
            statement_id = f"{record_id}-S{idx:03d}"
            base = {
                "statement_id": statement_id,
                "source_spans": [
                    self._span_builder.build(record, q.json_path, q.quote) for q in stmt.quotes
                ],
                "annotation_status": "pending_review",
                "support_status": "unverified",
                "note": stmt.note,
                "statement_type": stmt.statement_type,
            }
            if stmt.statement_type == "case_observation":
                base["subject"] = stmt.subject
            elif stmt.statement_type == "cause_claim":
                base.update(subject=stmt.subject, relation=stmt.relation, objects=stmt.objects, scope_text=stmt.scope_text)
            elif stmt.statement_type == "ingredient_effect_claim":
                base.update(
                    subject=self._matching_stage.resolve(stmt.subject),
                    object=stmt.object,
                    concentration_raw=stmt.concentration_raw,
                )
            elif stmt.statement_type == "precaution":
                base.update(subject=stmt.subject, relation=stmt.relation)
            elif stmt.statement_type == "usage_instruction":
                base.update(
                    action_id=stmt.action_id,
                    action=stmt.action,
                    time_of_day=stmt.time_of_day,
                    frequency=stmt.frequency.model_dump() if stmt.frequency else None,
                    ingredient_ids=[],
                )
            elif stmt.statement_type == "combination_claim":
                base.update(
                    subjects=[self._matching_stage.resolve(s) for s in stmt.subjects],
                    subject_plural_mode=stmt.subject_plural_mode,
                    object=stmt.object,
                )
            elif stmt.statement_type == "contextual_factor":
                base.update(
                    factor_raw=stmt.factor_raw,
                    details_raw=stmt.details_raw,
                    priority_raw=stmt.priority_raw,
                    causal_link_status=stmt.causal_link_status,
                )
            statements.append(base)
        return statements

    def _build_case_context(self, record: dict) -> dict:
        meta = record["meta"]
        question = record["info"]["question"]
        age_match = _AGE_TEXT_RE.search(question)
        return {
            "age_raw": meta.get("age"),
            "age_text_raw": age_match.group(0) if age_match else None,
            "gender_raw": meta.get("gender"),
            "skin_type_raw": meta.get("skin_type"),
            "skin_concerns_raw": meta.get("skin_concerns", []),
            "initial_skin_condition_raw": meta.get("initial_skin_condition"),
        }

    def _build_source(self, record_id: str, record: dict) -> dict:
        prov = self._provenance.get(record_id)
        if prov is None:
            raise ValueError(f"provenance 없음(구조 감사에 없는 record): {record_id}")
        return {
            "kind": "training_zip_record",
            "record_id": record_id,
            "source_archive": prov.source_archive,
            "source_hash": None,
            "dataset_split": prov.dataset_split,
            "info_target_concern": prov.info_target_concern,
            "archive_name_target_concern_mismatch": prov.archive_mismatch,
        }

    def _build_references(self, record: dict) -> list[dict]:
        refs = []
        for raw in record["info"].get("evidence_sources", []):
            is_placeholder = any(p.match(raw) for p in KNOWN_PLACEHOLDER_PATTERNS)
            refs.append(
                {
                    "raw": raw,
                    "reference_status": "placeholder_detected" if is_placeholder else "unverified",
                    "statement_links": [],
                }
            )
        return refs


def _needs_review(raw_doc: dict) -> list[str]:
    reasons = []
    for stmt in raw_doc["statements"]:
        subjects = []
        if stmt["statement_type"] == "ingredient_effect_claim":
            subjects = [stmt["subject"]]
        elif stmt["statement_type"] == "combination_claim":
            subjects = stmt["subjects"]
            if stmt["subject_plural_mode"] == "uncertain":
                reasons.append(f"{stmt['statement_id']}: combination_claim uncertain")
        for subj in subjects:
            if subj["matching_status"] != "matched":
                reasons.append(f"{stmt['statement_id']}: ingredient {subj['matching_status']} ({subj['raw_name']})")
    for ref in raw_doc["references"]:
        if ref["reference_status"] == "unverified":
            reasons.append(f"reference unverified: {ref['raw']}")
    return reasons


async def _run() -> None:
    records = {}
    with _RECORDS_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            rec = json.loads(line)
            records[rec["info"]["id"]] = rec

    provenance = NiaRecordProvenanceIndex()
    sample_ids = NiaPilotSampler(provenance).sample(records, _PILOT_SIZE)

    completed_ids: set[str] = set()
    if _CHECKPOINT_PATH.exists():
        completed_ids = set(_CHECKPOINT_PATH.read_text(encoding="utf-8").splitlines())

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            candidates = await IngredientMasterRepository(session).list_all_as_candidates()
    finally:
        await database.dispose()
    matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
    matching_stage = NiaIngredientMatchingStage(matcher)

    if settings.openai is None:
        raise RuntimeError("config.yaml에 openai 블록이 없어 NIA LLM 라벨링을 실행할 수 없습니다.")
    labeler = NiaLlmLabeler(settings.openai)
    span_builder = NiaSourceSpanBuilder()
    processor = NiaPilotRecordProcessor(labeler, span_builder, matching_stage, provenance)

    raw_docs: list[dict] = []
    raw_records_companion: dict[str, dict] = {}
    failures: list[dict] = []

    for record_id in sample_ids:
        if record_id in completed_ids:
            continue
        record = records[record_id]
        raw_records_companion[record_id] = {"zip_name": provenance.get(record_id).source_archive, "record": record}
        try:
            raw_doc = await processor.process(record_id, record)
        except (NiaSourceSpanBuildError, Exception) as exc:  # noqa: BLE001 - 실패 사유를 그대로 기록
            failures.append({"record_id": record_id, "stage": "labeling", "error": str(exc), "retry_count": 0})
            continue
        raw_docs.append(raw_doc)
        with _CHECKPOINT_PATH.open("a", encoding="utf-8") as ckpt:
            ckpt.write(record_id + "\n")

    _RAW_RECORDS_COMPANION_PATH.write_text(
        json.dumps(raw_records_companion, ensure_ascii=False), encoding="utf-8"
    )
    labeling_tmp_path = Path("data/processed/.nia_10s_30s_pilot_raw_docs.json")
    labeling_tmp_path.write_text(json.dumps(raw_docs, ensure_ascii=False), encoding="utf-8")

    reports = NiaLabelingParser().parse_file(labeling_tmp_path, _RAW_RECORDS_COMPANION_PATH)
    report_by_id = {r.record_id: r for r in reports}

    passed_docs = []
    review_queue = []
    for raw_doc in raw_docs:
        rid = raw_doc["source"]["record_id"]
        report = report_by_id.get(rid)
        if report is None or not report.ok:
            failures.append(
                {
                    "record_id": rid,
                    "stage": "parser_validation",
                    "error": "; ".join(report.schema_errors + report.span_errors + tuple(report.invariant_errors))
                    if report
                    else "report missing",
                    "retry_count": 0,
                }
            )
            continue
        passed_docs.append(raw_doc)
        review_reasons = _needs_review(raw_doc) + [f"warning: {w}" for w in report.warnings]
        if review_reasons:
            review_queue.append({"record_id": rid, "reasons": review_reasons})

    with _ANNOTATIONS_PATH.open("w", encoding="utf-8") as f:
        for doc in passed_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    with _FAILURES_PATH.open("w", encoding="utf-8") as f:
        for fail in failures:
            f.write(json.dumps(fail, ensure_ascii=False) + "\n")
    with _REVIEW_QUEUE_PATH.open("w", encoding="utf-8") as f:
        for item in review_queue:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"pilot 대상 {len(sample_ids)}건, 처리 시도 {len(raw_docs) + len(failures)}건")
    print(f"parser 통과: {len(passed_docs)}건, 실패: {len(failures)}건, review_queue: {len(review_queue)}건")
    print(f"저장: {_ANNOTATIONS_PATH}, {_FAILURES_PATH}, {_REVIEW_QUEUE_PATH}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run())
