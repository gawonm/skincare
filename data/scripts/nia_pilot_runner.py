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

from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from core.config import settings
from core.database import Database
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.nia_claim_ingestion_policy import NiaClaimIngestionPolicy
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_labeling_parser import KNOWN_PLACEHOLDER_PATTERNS, NiaLabelingParser
from data.scripts.nia_llm_label_schemas import LlmNiaLabelingOutput
from data.scripts.nia_llm_labeler import NiaLlmLabeler
from data.scripts.nia_record_provenance import NiaRecordProvenanceIndex
from data.scripts.nia_reference_linker import NiaReferenceLinker
from data.scripts.nia_semantic_span_validator import NiaSemanticSpanValidator
from data.scripts.nia_source_span_builder import NiaSourceSpanBuilder, NiaSourceSpanBuildError
from data.scripts.nia_usage_instruction_normalizer import NiaUsageInstructionNormalizer

_RECORDS_PATH = Path("data/processed/nia_qa_10s_30s.jsonl")
_PILOT_SIZE = 40
_SCHEMA_VERSION = "1.1"
_ANNOTATION_VERSION = "llm-pilot-2026-09-14"

_ANNOTATIONS_PATH = Path("data/processed/nia_10s_30s_annotations.jsonl")
_FAILURES_PATH = Path("data/processed/nia_10s_30s_labeling_failures.jsonl")
_REVIEW_QUEUE_PATH = Path("data/processed/nia_10s_30s_review_queue.jsonl")
_CLAIM_INGESTION_PATH = Path("data/processed/nia_10s_30s_claim_ingestion.jsonl")
_CHECKPOINT_PATH = Path("data/processed/.nia_10s_30s_pilot_checkpoint.txt")
_RAW_RECORDS_COMPANION_PATH = Path("data/processed/.nia_10s_30s_pilot_raw_records.json")

_AGE_TEXT_RE = re.compile(r"\d+세")
# review_reasons 문자열 중 Claim RAG ingestion을 막거나 human review로 보내야 하는 것만
# blocking으로 분류한다. ingredient unresolved/reference unverified/parser soft warning은
# NIA가 evidence source가 아니라 claim layer일 뿐이므로 non-blocking이다(사용자 지정 정책).
_BLOCKING_REASON_MARKERS = ("span_semantic_mismatch", "span_semantic_confidence_low", "span fuzzy")


def _is_blocking_reason(reason: str) -> bool:
    return any(marker in reason for marker in _BLOCKING_REASON_MARKERS)


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
        self._usage_normalizer = NiaUsageInstructionNormalizer()
        self._semantic_validator = NiaSemanticSpanValidator()
        self._reference_linker = NiaReferenceLinker()
        self._ingestion_policy = NiaClaimIngestionPolicy()

    async def process(self, record_id: str, record: dict) -> tuple[dict, list[str], list[dict]]:
        """LLM 라벨링 + deterministic 후처리를 거쳐 `NiaLabelingDocument` 형태의 raw dict를 만든다.
        실패(quote 원문 복원 전부 실패 등)는 예외로 전파해 호출부가 failures로 분류한다.
        두 번째 반환값은 review 대상 사유 목록, 세 번째는 statement별 Claim RAG ingestion
        결정 목록이다(review 대상 여부와 ingestion 가부는 서로 다른 축이다)."""
        llm_output = await self._labeler.label(record)
        statements, review_reasons, ingestion_records = self._build_statements(
            record_id, record, llm_output
        )
        references = self._reference_linker.link(self._build_references(record), statements)
        annotation_version = f"{_ANNOTATION_VERSION}-{self._labeler.provider}-{self._labeler.model}"
        doc = {
            "schema_version": _SCHEMA_VERSION,
            "annotation_version": annotation_version,
            "is_example": False,
            "is_partial_annotation": True,
            "production_ready": False,
            "annotator_count": 1,
            "source": self._build_source(record_id, record),
            "case_context": self._build_case_context(record),
            "statements": statements,
            "references": references,
            "notes": ["LLM 자동 라벨링 결과, 사람 검토 전(pending_review)."],
        }
        return doc, review_reasons, ingestion_records

    def _build_statements(
        self, record_id: str, record: dict, llm_output: LlmNiaLabelingOutput
    ) -> tuple[list[dict], list[str], list[dict]]:
        statements = []
        review_reasons: list[str] = []
        ingestion_records: list[dict] = []
        for idx, stmt in enumerate(llm_output.statements, start=1):
            statement_id = f"{record_id}-S{idx:03d}"
            spans = []
            has_low_confidence_span = False
            for q in stmt.quotes:
                span, confidence = self._span_builder.build(record, q.json_path, q.quote)
                spans.append(span)
                if confidence == "fuzzy":
                    has_low_confidence_span = True
                    review_reasons.append(
                        f"{statement_id}: span fuzzy 복원(신뢰도 낮음) quote={span['quote']!r}"
                    )
            base = {
                "statement_id": statement_id,
                "source_spans": spans,
                "annotation_status": "pending_review",
                "support_status": "unverified",
                "note": stmt.note,
                "statement_type": stmt.statement_type,
            }
            if stmt.statement_type == "case_observation":
                base["subject"] = stmt.subject
            elif stmt.statement_type == "cause_claim":
                base.update(
                    subject=stmt.subject,
                    relation=stmt.relation,
                    objects=stmt.objects,
                    scope_text=stmt.scope_text,
                )
            elif stmt.statement_type == "ingredient_effect_claim":
                base.update(
                    subject=self._matching_stage.resolve(stmt.subject),
                    object=stmt.object,
                    concentration_raw=stmt.concentration_raw,
                )
            elif stmt.statement_type == "precaution":
                base.update(subject=stmt.subject, relation=stmt.relation)
            elif stmt.statement_type == "usage_instruction":
                quote_text = " ".join(span["quote"] for span in spans)
                time_of_day, frequency = self._usage_normalizer.normalize(
                    quote_text,
                    stmt.time_of_day,
                    stmt.frequency.model_dump() if stmt.frequency else None,
                )
                # unresolved mention은 임의 ingredient_id로 바꾸지 않고 그냥 뺀다 - 이
                # 필드엔 raw_name을 보존할 자리가 없어(NiaUsageInstructionStatement.
                # ingredient_ids: tuple[UUID, ...]), matched만 담는 게 유일한 안전한 방법이다.
                resolved_mentions = [
                    self._matching_stage.resolve(mention) for mention in stmt.ingredient_mentions
                ]
                base.update(
                    action_id=stmt.action_id,
                    action=stmt.action,
                    time_of_day=time_of_day,
                    frequency=frequency,
                    ingredient_ids=[
                        resolved["ingredient_id"]
                        for resolved in resolved_mentions
                        if resolved["matching_status"] == "matched"
                    ],
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
            result = self._semantic_validator.check(base)
            if result.verdict == "mismatch":
                base["annotation_status"] = "rejected"
                review_reasons.append(
                    f"{statement_id}: span_semantic_mismatch (score={result.score:.2f})"
                )
            elif result.verdict == "low_confidence":
                review_reasons.append(
                    f"{statement_id}: span_semantic_confidence_low (score={result.score:.2f})"
                )
            statements.append(base)

            decision = self._ingestion_policy.decide(
                base,
                semantic_verdict=result.verdict,
                has_low_confidence_span=has_low_confidence_span,
            )
            ingestion_records.append(
                {
                    "record_id": record_id,
                    "statement_id": statement_id,
                    "statement_type": base["statement_type"],
                    "decision": decision.value,
                    "priority": self._ingestion_policy.priority(base).value,
                }
            )
        return statements, review_reasons, ingestion_records

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
                reasons.append(
                    f"{stmt['statement_id']}: ingredient {subj['matching_status']} ({subj['raw_name']})"
                )
    for ref in raw_doc["references"]:
        if ref["reference_status"] == "unverified":
            reasons.append(f"reference unverified: {ref['raw']}")
    return reasons


def _load_records() -> dict[str, dict]:
    records = {}
    with _RECORDS_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            rec = json.loads(line)
            records[rec["info"]["id"]] = rec
    return records


def _append_checkpoint(record_id: str) -> None:
    with _CHECKPOINT_PATH.open("a", encoding="utf-8") as ckpt:
        ckpt.write(record_id + "\n")


def _write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


async def _run() -> None:
    records = _load_records()

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

    if settings.agent.chat.provider.value == "openai" and settings.openai is None:
        raise RuntimeError(
            "provider=openai인데 config.yaml에 openai 블록이 없어 실행할 수 없습니다."
        )
    labeler = NiaLlmLabeler(settings.agent.chat, settings.openai)
    print(
        f"LLM provider={labeler.provider} model={labeler.model}"
        + (f" base_url={labeler.base_url}" if labeler.base_url else "")
    )
    span_builder = NiaSourceSpanBuilder()
    processor = NiaPilotRecordProcessor(labeler, span_builder, matching_stage, provenance)

    raw_docs: list[dict] = []
    raw_records_companion: dict[str, dict] = {}
    failures: list[dict] = []
    low_confidence_by_record: dict[str, list[str]] = {}
    ingestion_records_by_record: dict[str, list[dict]] = {}

    for record_id in sample_ids:
        if record_id in completed_ids:
            continue
        record = records[record_id]
        raw_records_companion[record_id] = {
            "zip_name": provenance.get(record_id).source_archive,
            "record": record,
        }
        try:
            raw_doc, review_reasons, ingestion_records = await processor.process(record_id, record)
        except (NiaSourceSpanBuildError, Exception) as exc:  # noqa: BLE001 - 실패 사유를 그대로 기록
            failures.append(
                {"record_id": record_id, "stage": "labeling", "error": str(exc), "retry_count": 0}
            )
            continue
        raw_docs.append(raw_doc)
        if review_reasons:
            low_confidence_by_record[record_id] = review_reasons
        ingestion_records_by_record[record_id] = ingestion_records
        _append_checkpoint(record_id)

    _RAW_RECORDS_COMPANION_PATH.write_text(
        json.dumps(raw_records_companion, ensure_ascii=False), encoding="utf-8"
    )
    labeling_tmp_path = Path("data/processed/.nia_10s_30s_pilot_raw_docs.json")
    labeling_tmp_path.write_text(json.dumps(raw_docs, ensure_ascii=False), encoding="utf-8")

    reports = NiaLabelingParser().parse_file(labeling_tmp_path, _RAW_RECORDS_COMPANION_PATH)
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
            + low_confidence_by_record.get(rid, [])
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

    _write_jsonl(_ANNOTATIONS_PATH, passed_docs)
    _write_jsonl(_FAILURES_PATH, failures)
    _write_jsonl(_REVIEW_QUEUE_PATH, review_queue)
    _write_jsonl(_CLAIM_INGESTION_PATH, claim_ingestion)

    ingestible = sum(
        1
        for i in claim_ingestion
        if i["decision"] in ("ingestible_structured", "ingestible_free_text")
    )
    print(f"pilot 대상 {len(sample_ids)}건, 처리 시도 {len(raw_docs) + len(failures)}건")
    print(
        f"parser 통과: {len(passed_docs)}건, 실패: {len(failures)}건, review_queue: {len(review_queue)}건"
    )
    print(f"claim ingestion: {len(claim_ingestion)}개 statement 중 {ingestible}개 즉시 ingest 가능")
    print(
        f"저장: {_ANNOTATIONS_PATH}, {_FAILURES_PATH}, {_REVIEW_QUEUE_PATH}, {_CLAIM_INGESTION_PATH}"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run())
