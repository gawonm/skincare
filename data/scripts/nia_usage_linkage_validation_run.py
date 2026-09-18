"""usage_instruction ingredient linkage 수정(`nia_llm_label_schemas.LlmUsageInstructionStatement.
ingredient_mentions` + `nia_pilot_runner.py`의 매칭 연결)이 실제 LLM 응답에서도 동작하는지
검증하는 1회성 validation run.

기존 GPT-4o-mini baseline(`data/processed/nia_10s_30s_annotations.jsonl`, 36건, annotation_version=
llm-pilot-2026-09-14-openai-gpt-4o-mini)과 **정확히 동일한 36개 record_id**만, **별도 output
경로**에 다시 라벨링한다 - baseline 파일은 절대 덮어쓰지 않는다. `NiaPilotRecordProcessor` 등
기존 pipeline 클래스를 그대로 재사용하고, 이 스크립트는 (1) 대상 record_id를 baseline에서
읽어와 일치를 검증하고 (2) 출력 경로만 분리하고 (3) annotation_version만
`llm-validation-<날짜>-<provider>-<model>`로 덮어쓴다 - 그 외 라벨링 로직은 전혀 건드리지 않는다.

전체 3,581건 실행이 아니다. `data/manual_review/nia/`의 58건도 쓰지 않는다.

사용법:
    uv run python -m data.scripts.nia_usage_linkage_validation_run
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from core.config import settings
from core.database import Database
from data.scripts.nia_labeling_schemas import NiaLabelingDocument
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_labeling_parser import NiaLabelingParser
from data.scripts.nia_llm_labeler import NiaLlmLabeler
from data.scripts.nia_pilot_runner import (
    NiaPilotRecordProcessor,
    _is_blocking_reason,
    _needs_review,
)
from data.scripts.nia_record_provenance import NiaRecordProvenanceIndex
from data.scripts.nia_source_span_builder import NiaSourceSpanBuilder, NiaSourceSpanBuildError

_BASELINE_ANNOTATIONS_PATH = Path("data/processed/nia_10s_30s_annotations.jsonl")
_QA_CORPUS_PATH = Path("data/processed/nia_qa_10s_30s.jsonl")

_VALIDATION_PREFIX = f"llm-validation-{datetime.now(UTC).date().isoformat()}"

_OUT_DIR = Path("data/processed")
_VALIDATION_ANNOTATIONS_PATH = _OUT_DIR / "nia_10s_30s_annotations_usage_linkage_validation.jsonl"
_VALIDATION_FAILURES_PATH = (
    _OUT_DIR / "nia_10s_30s_labeling_failures_usage_linkage_validation.jsonl"
)
_VALIDATION_REVIEW_QUEUE_PATH = _OUT_DIR / "nia_10s_30s_review_queue_usage_linkage_validation.jsonl"
_VALIDATION_CLAIM_INGESTION_PATH = (
    _OUT_DIR / "nia_10s_30s_claim_ingestion_usage_linkage_validation.jsonl"
)
_VALIDATION_RAW_DOCS_TMP_PATH = _OUT_DIR / ".nia_usage_linkage_validation_raw_docs.json"
_VALIDATION_RAW_RECORDS_TMP_PATH = _OUT_DIR / ".nia_usage_linkage_validation_raw_records.json"


class BaselineRecordIdMismatchError(RuntimeError):
    """검증 대상 record_id 집합이 baseline과 다르면 실행 자체를 막는다(사용자 지시)."""


def _load_baseline_record_ids() -> list[str]:
    docs = []
    with _BASELINE_ANNOTATIONS_PATH.open("r", encoding="utf-8") as f:
        docs = [NiaLabelingDocument.model_validate_json(line) for line in f]
    return [doc.source.record_id for doc in docs]


def _load_qa_corpus() -> dict[str, dict]:
    records: dict[str, dict] = {}
    with _QA_CORPUS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            records[rec["info"]["id"]] = rec
    return records


def _write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


async def _run() -> None:
    baseline_ids = _load_baseline_record_ids()
    qa_corpus = _load_qa_corpus()

    target_ids = [rid for rid in baseline_ids if rid in qa_corpus]
    if set(target_ids) != set(baseline_ids):
        missing = sorted(set(baseline_ids) - set(qa_corpus))
        raise BaselineRecordIdMismatchError(
            f"baseline record_id {len(baseline_ids)}건 중 {len(missing)}건이 "
            f"10~30대 corpus(nia_qa_10s_30s.jsonl)에 없습니다: {missing}"
        )

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            candidates = await IngredientMasterRepository(session).list_all_as_candidates()
    finally:
        await database.dispose()
    matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
    matching_stage = NiaIngredientMatchingStage(matcher)

    if settings.agent.chat.provider.value == "openai" and settings.openai is None:
        raise RuntimeError(
            "provider=openai인데 config.yaml에 openai 블록이 없어 실행할 수 없습니다."
        )
    labeler = NiaLlmLabeler(settings.agent.chat, settings.openai)
    validation_annotation_version = f"{_VALIDATION_PREFIX}-{labeler.provider}-{labeler.model}"
    print(
        f"validation LLM provider={labeler.provider} model={labeler.model} "
        f"annotation_version={validation_annotation_version}"
    )

    span_builder = NiaSourceSpanBuilder()
    provenance = NiaRecordProvenanceIndex()
    processor = NiaPilotRecordProcessor(labeler, span_builder, matching_stage, provenance)

    raw_docs: list[dict] = []
    raw_records_companion: dict[str, dict] = {}
    failures: list[dict] = []
    review_reasons_by_record: dict[str, list[str]] = {}
    ingestion_records_by_record: dict[str, list[dict]] = {}

    for record_id in target_ids:
        record = qa_corpus[record_id]
        raw_records_companion[record_id] = {
            "zip_name": provenance.get(record_id).source_archive
            if provenance.get(record_id)
            else None,
            "record": record,
        }
        try:
            raw_doc, review_reasons, ingestion_records = await processor.process(record_id, record)
        except (NiaSourceSpanBuildError, Exception) as exc:  # noqa: BLE001 - 실패 사유 그대로 기록
            failures.append(
                {"record_id": record_id, "stage": "labeling", "error": str(exc), "retry_count": 0}
            )
            continue
        # baseline과 dataset을 구분하기 위해 annotation_version만 validation 전용 값으로
        # 덮어쓴다 - 그 외 라벨링 결과(statements 등)는 전혀 수정하지 않는다.
        raw_doc["annotation_version"] = validation_annotation_version
        raw_docs.append(raw_doc)
        if review_reasons:
            review_reasons_by_record[record_id] = review_reasons
        ingestion_records_by_record[record_id] = ingestion_records

    _VALIDATION_RAW_RECORDS_TMP_PATH.write_text(
        json.dumps(raw_records_companion, ensure_ascii=False), encoding="utf-8"
    )
    _VALIDATION_RAW_DOCS_TMP_PATH.write_text(
        json.dumps(raw_docs, ensure_ascii=False), encoding="utf-8"
    )

    reports = NiaLabelingParser().parse_file(
        _VALIDATION_RAW_DOCS_TMP_PATH, _VALIDATION_RAW_RECORDS_TMP_PATH
    )
    report_by_id = {r.record_id: r for r in reports}

    passed_docs = []
    review_queue = []
    claim_ingestion: list[dict] = []
    for raw_doc in raw_docs:
        rid = raw_doc["source"]["record_id"]
        report = report_by_id.get(rid)
        if report is None or not report.ok:
            failures.append(
                {
                    "record_id": rid,
                    "stage": "parser_validation",
                    "error": "; ".join(
                        report.schema_errors + report.span_errors + tuple(report.invariant_errors)
                    )
                    if report
                    else "report missing",
                    "retry_count": 0,
                }
            )
            continue
        passed_docs.append(raw_doc)
        all_reasons = (
            _needs_review(raw_doc)
            + [f"warning: {w}" for w in report.warnings]
            + review_reasons_by_record.get(rid, [])
        )
        if all_reasons:
            blocking = [r for r in all_reasons if _is_blocking_reason(r)]
            non_blocking = [r for r in all_reasons if not _is_blocking_reason(r)]
            review_queue.append(
                {
                    "record_id": rid,
                    "blocking_reasons": blocking,
                    "non_blocking_reasons": non_blocking,
                }
            )
        claim_ingestion.extend(ingestion_records_by_record.get(rid, []))

    _write_jsonl(_VALIDATION_ANNOTATIONS_PATH, passed_docs)
    _write_jsonl(_VALIDATION_FAILURES_PATH, failures)
    _write_jsonl(_VALIDATION_REVIEW_QUEUE_PATH, review_queue)
    _write_jsonl(_VALIDATION_CLAIM_INGESTION_PATH, claim_ingestion)

    print(
        f"validation 대상 {len(target_ids)}건, parser 통과 {len(passed_docs)}건, 실패 {len(failures)}건"
    )
    print(
        f"저장: {_VALIDATION_ANNOTATIONS_PATH}, {_VALIDATION_FAILURES_PATH}, "
        f"{_VALIDATION_REVIEW_QUEUE_PATH}, {_VALIDATION_CLAIM_INGESTION_PATH}"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run())
