"""3,581건 전체(10~30대 target corpus) NIA production annotation 전용 entrypoint.

`nia_pilot_runner.py`는 `_PILOT_SIZE=40`짜리 stratified sampler로 파일럿 규모만 처리하도록
만들어져 있어 production(3,581건) 실행에는 그대로 쓸 수 없다 - 이 모듈은 그 sampler를 쓰지
않고 corpus 전체를 순회하는 별도 entrypoint를 제공한다. 다만 labeling/ingredient matching/
schema 검증 로직(`NiaPilotRecordProcessor`, `NiaIngredientMatchingStage`, `NiaLabelingParser`,
`NiaClaimIngestionPolicy`)은 전부 기존 코드를 그대로 재사용한다 - 새 annotation 로직을 만들지
않는다.

핵심 설계 - "출력 파일 존재 여부가 유일한 완료 판정 기준"
    record 하나가 성공(라벨링 + 단건 parser 검증 통과)할 때마다 그 즉시
    production annotation JSONL에 한 줄을 append + flush + fsync한다. 재실행 시
    체크포인트 파일이 아니라 **이 출력 파일에 실제로 존재하는 record_id**만 "완료"로
    인정한다(체크포인트는 "시도했다"만 알고 "결과가 저장됐다"는 보장하지 못하기 때문 -
    `docs/data/README.md`가 이미 문서화한 "대량 수집은 반드시 증분 저장" 교훈과 동일한
    이유). 이러면 프로세스가 어느 시점에 죽어도 그 직전까지 성공한 record는 파일에 남고,
    재실행은 그 파일에 없는 record_id부터만 이어서 처리한다 - 중복도, 유실도 없다.

review_queue/claim_ingestion은 Phase 2로 분리한다 - production annotation JSONL(권위 있는
단일 소스)과 그 옆의 review-signal 보조 파일(`review_reasons`만 담음, non-authoritative)에서
매번 처음부터 다시 계산해 덮어쓴다. 두 파일 다 LLM 호출 없이 완전히 결정적으로 재생성되므로
"일부만 쓰고 나머지가 없는" 상태가 존재할 수 없다 - 항상 그 시점까지의 annotation 전체를
반영해 통째로 다시 쓴다.

사용법:
    uv run python -m data.scripts.nia_production_annotation_run
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from core.config import settings
from core.database import Database
from data.scripts.nia_labeling_schemas import NiaLabelingDocument
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.nia_claim_ingestion_policy import NiaClaimIngestionPolicy
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_labeling_parser import DocumentReport, NiaLabelingParser
from data.scripts.nia_llm_labeler import NiaLlmLabeler
from data.scripts.nia_pilot_runner import (
    NiaPilotRecordProcessor,
    _is_blocking_reason,
    _needs_review,
)
from data.scripts.nia_record_provenance import NiaRecordProvenanceIndex
from data.scripts.nia_source_span_builder import NiaSourceSpanBuilder

_QA_CORPUS_PATH = Path("data/processed/nia_qa_10s_30s.jsonl")

_OUT_DIR = Path("data/processed")
_PRODUCTION_ANNOTATIONS_PATH = _OUT_DIR / "nia_10s_30s_annotations_production.jsonl"
_PRODUCTION_FAILURES_PATH = _OUT_DIR / "nia_10s_30s_labeling_failures_production.jsonl"
_PRODUCTION_REVIEW_SIGNALS_PATH = _OUT_DIR / "nia_10s_30s_review_signals_production.jsonl"
_PRODUCTION_REVIEW_QUEUE_PATH = _OUT_DIR / "nia_10s_30s_review_queue_production.jsonl"
_PRODUCTION_CLAIM_INGESTION_PATH = _OUT_DIR / "nia_10s_30s_claim_ingestion_production.jsonl"

_PARSER_SCRATCH_DOC_PATH = _OUT_DIR / ".nia_production_parser_scratch_doc.json"
_PARSER_SCRATCH_RECORD_PATH = _OUT_DIR / ".nia_production_parser_scratch_record.json"

# 이 production corpus 전체(resume 포함)가 공유하는 유일한 annotation_version.
# 과거에는 실행 시점의 wall-clock 날짜로 매번 새로 계산했는데, 그 상태로 resume하다가 날짜가
# 바뀌면 같은 논리적 production run 안에 서로 다른 annotation_version이 섞여 버렸다(1~889번째
# 줄은 09-17, 890~1497번째 줄은 09-18). 날짜와 무관하게 고정된 값을 쓰도록 상수로 못 박는다.
# provider/model이 바뀌면 이 상수도 더 이상 맞지 않으므로 `_run()`에서 그 조합을 검증한다.
_CANONICAL_PRODUCTION_ANNOTATION_VERSION = "llm-production-2026-09-17-openai-gpt-4o-mini"

_CANONICAL_PRODUCTION_PROVIDER = "openai"
_CANONICAL_PRODUCTION_MODEL = "gpt-4o-mini"

# nia_pilot_runner.py의 review_reasons 문자열과 동일한 markers - 새로 만들지 않고 그대로 맞춘다.
_BLOCKING_REASON_MARKERS = ("span_semantic_mismatch", "span_semantic_confidence_low", "span fuzzy")


class NiaProductionOutputIntegrityError(RuntimeError):
    """기존 production 출력 파일이 손상됐거나 신뢰할 수 없을 때 fail-fast용."""


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _append_jsonl(path: Path, item: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _load_qa_corpus() -> dict[str, dict]:
    records: dict[str, dict] = {}
    with _QA_CORPUS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            records[rec["info"]["id"]] = rec
    return records


class NiaProductionAnnotationStore:
    """production annotation JSONL 하나의 무결성 검사 + append 전담. 이 파일에 실제로
    존재하는 record_id만 "완료"로 인정하는, 이 스크립트의 유일한 authoritative resume source."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load_completed_record_ids(self, valid_record_ids: set[str]) -> set[str]:
        """기존 파일을 줄 단위로 검증하며 읽는다. 파싱 실패/중복 record_id/corpus에 없는
        record_id 중 하나라도 있으면 LLM 호출 전에 즉시 실패시킨다(사용자 지시)."""
        if not self._path.exists():
            return set()
        completed: set[str] = set()
        versions: set[str] = set()
        with self._path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    doc = NiaLabelingDocument.model_validate_json(line)
                except Exception as exc:
                    raise NiaProductionOutputIntegrityError(
                        f"{self._path}:{line_no} 파싱 실패 - 파일이 손상되었을 수 있습니다: {exc}"
                    ) from exc
                rid = doc.source.record_id
                if rid in completed:
                    raise NiaProductionOutputIntegrityError(
                        f"{self._path}:{line_no} record_id 중복: {rid!r}"
                    )
                if rid not in valid_record_ids:
                    raise NiaProductionOutputIntegrityError(
                        f"{self._path}:{line_no} record_id {rid!r}가 input corpus(nia_qa_10s_30s.jsonl)에 없습니다"
                    )
                # 하나의 논리적 production run은 annotation_version이 하나여야 한다 - 섞여
                # 있으면(예: resume 도중 날짜가 바뀌어 버전이 자동으로 달라짐) silent continue
                # 하지 말고 여기서 즉시 멈춘다.
                versions.add(doc.annotation_version)
                if len(versions) > 1:
                    raise NiaProductionOutputIntegrityError(
                        f"{self._path}:{line_no} annotation_version이 섞여 있습니다: {sorted(versions)!r} "
                        "- 하나의 production run은 annotation_version이 하나여야 합니다"
                    )
                completed.add(rid)
        return completed

    def append(self, raw_doc: dict) -> None:
        _append_jsonl(self._path, raw_doc)


@dataclass
class ProcessOneRecordResult:
    status: str  # "ok" | "failed"
    raw_doc: dict | None
    review_reasons: list[str]
    error: str | None


def _validate_single_doc(parser: NiaLabelingParser, raw_doc: dict, record: dict) -> DocumentReport:
    """`NiaLabelingParser.parse_file()`을 batch 1건짜리 scratch 파일로 호출한다 - 새 검증
    로직을 만들지 않고 기존 공개 API를 그대로 재사용한다. scratch 파일은 매 호출마다
    덮어써서 재사용한다(record마다 새 파일을 만들지 않음)."""
    _PARSER_SCRATCH_DOC_PATH.write_text(json.dumps([raw_doc], ensure_ascii=False), encoding="utf-8")
    _PARSER_SCRATCH_RECORD_PATH.write_text(
        json.dumps({raw_doc["source"]["record_id"]: {"record": record}}, ensure_ascii=False),
        encoding="utf-8",
    )
    reports = parser.parse_file(_PARSER_SCRATCH_DOC_PATH, _PARSER_SCRATCH_RECORD_PATH)
    return reports[0]


async def process_one_record(
    processor: NiaPilotRecordProcessor,
    parser: NiaLabelingParser,
    record_id: str,
    record: dict,
    annotation_version: str,
) -> ProcessOneRecordResult:
    """LLM 라벨링 + 단건 parser 검증까지만 하고 반환한다(파일 쓰기는 호출부 책임 -
    순수 함수에 가깝게 유지해 LLM 호출 없이도 조합 테스트가 가능하게 한다)."""
    try:
        raw_doc, review_reasons, _ingestion_records_unused = await processor.process(
            record_id, record
        )
    except Exception as exc:  # noqa: BLE001 - 실패 사유를 그대로 드러낸다
        return ProcessOneRecordResult("failed", None, [], f"labeling: {exc}")

    report = _validate_single_doc(parser, raw_doc, record)
    if not report.ok:
        error = "; ".join(
            report.schema_errors + report.span_errors + tuple(report.invariant_errors)
        )
        return ProcessOneRecordResult("failed", None, [], f"parser_validation: {error}")

    raw_doc["annotation_version"] = annotation_version
    all_reasons = review_reasons + [f"warning: {w}" for w in report.warnings]
    return ProcessOneRecordResult("ok", raw_doc, all_reasons, None)


class NiaProductionAnnotationRunner:
    """record 하나 처리 후 즉시 파일에 반영(append+flush+fsync)한다 - 배치로 모았다가 끝에
    한 번에 쓰지 않는다. 이미 완료된 record_id는 절대 다시 처리하지 않는다(중복 방지)."""

    def __init__(
        self,
        processor: NiaPilotRecordProcessor,
        parser: NiaLabelingParser,
        annotations_store: NiaProductionAnnotationStore,
        failures_path: Path,
        review_signals_path: Path,
        annotation_version: str,
    ) -> None:
        self._processor = processor
        self._parser = parser
        self._annotations_store = annotations_store
        self._failures_path = failures_path
        self._review_signals_path = review_signals_path
        self._annotation_version = annotation_version

    async def run_one(self, record_id: str, record: dict, *, already_done: set[str]) -> str:
        if record_id in already_done:
            # 방어적 가드 - 정상 경로라면 호출부가 target_ids에서 이미 제외했어야 한다.
            return "skipped_already_done"

        result = await process_one_record(
            self._processor, self._parser, record_id, record, self._annotation_version
        )
        if result.status == "failed":
            _append_jsonl(
                self._failures_path,
                {"record_id": record_id, "stage": "production", "error": result.error},
            )
            return "failed"

        assert result.raw_doc is not None
        # review-signal을 annotation보다 먼저 써도(혹은 나중에 써도) authoritative 판정에는
        # 영향 없다 - resume은 오직 annotations_store에만 의존한다. 여기서는 review-signal을
        # 먼저 남겨 Phase 2가 최대한 풍부한 정보를 쓸 수 있게 한다.
        _append_jsonl(
            self._review_signals_path,
            {"record_id": record_id, "review_reasons": result.review_reasons},
        )
        self._annotations_store.append(result.raw_doc)
        return "ok"

    async def run_many(
        self, target_ids: list[str], records: dict[str, dict], already_done: set[str]
    ) -> None:
        for record_id in target_ids:
            await self.run_one(record_id, records[record_id], already_done=already_done)


def _reconstruct_semantic_verdict(statement_id: str, reasons: list[str]) -> tuple[str, bool]:
    """review-signal에 남은 문자열 marker로부터 원래 판정을 복원한다.
    `data/scripts/nia_reresolve_ingredients.py`가 이미 쓰는 것과 동일한 방식(새로 만들지 않음)."""
    stmt_reasons = [r for r in reasons if r.startswith(statement_id + ":")]
    has_fuzzy_span = any("span fuzzy" in r for r in stmt_reasons)
    has_mismatch = any("span_semantic_mismatch" in r for r in stmt_reasons)
    has_low_conf = any("span_semantic_confidence_low" in r for r in stmt_reasons)
    verdict = "mismatch" if has_mismatch else ("low_confidence" if has_low_conf else "ok")
    return verdict, has_fuzzy_span


def regenerate_downstream(
    annotations_path: Path,
    review_signals_path: Path,
    review_queue_path: Path,
    claim_ingestion_path: Path,
) -> None:
    """production annotation JSONL(권위 있는 소스) + review-signal 보조 파일만으로
    review_queue/claim_ingestion을 처음부터 다시 계산해 덮어쓴다. LLM 호출 없음,
    완전히 결정적 - 언제 다시 실행해도 그 시점의 annotation을 그대로 반영한다."""
    docs = _read_jsonl(annotations_path)
    signals_by_id = {
        row["record_id"]: row["review_reasons"] for row in _read_jsonl(review_signals_path)
    }
    policy = NiaClaimIngestionPolicy()

    review_queue: list[dict] = []
    claim_ingestion: list[dict] = []
    for raw_doc in docs:
        rid = raw_doc["source"]["record_id"]
        reasons = signals_by_id.get(rid, [])
        all_reasons = _needs_review(raw_doc) + reasons
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
        for stmt in raw_doc["statements"]:
            semantic_verdict, has_low_confidence_span = _reconstruct_semantic_verdict(
                stmt["statement_id"], reasons
            )
            decision = policy.decide(
                stmt,
                semantic_verdict=semantic_verdict,
                has_low_confidence_span=has_low_confidence_span,
            )
            claim_ingestion.append(
                {
                    "record_id": rid,
                    "statement_id": stmt["statement_id"],
                    "statement_type": stmt["statement_type"],
                    "decision": decision.value,
                    "priority": policy.priority(stmt).value,
                }
            )

    with review_queue_path.open("w", encoding="utf-8") as f:
        for row in review_queue:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with claim_ingestion_path.open("w", encoding="utf-8") as f:
        for row in claim_ingestion:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


async def _run() -> None:
    qa_corpus = _load_qa_corpus()
    store = NiaProductionAnnotationStore(_PRODUCTION_ANNOTATIONS_PATH)
    already_done = store.load_completed_record_ids(set(qa_corpus.keys()))
    target_ids = [rid for rid in qa_corpus if rid not in already_done]

    print(
        f"corpus 전체 {len(qa_corpus)}건, 이미 완료 {len(already_done)}건, 이번에 처리할 {len(target_ids)}건"
    )
    if not target_ids:
        print("처리할 record가 없습니다 - 이미 전부 완료됨.")
        regenerate_downstream(
            _PRODUCTION_ANNOTATIONS_PATH,
            _PRODUCTION_REVIEW_SIGNALS_PATH,
            _PRODUCTION_REVIEW_QUEUE_PATH,
            _PRODUCTION_CLAIM_INGESTION_PATH,
        )
        return

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
    if (
        labeler.provider != _CANONICAL_PRODUCTION_PROVIDER
        or labeler.model != _CANONICAL_PRODUCTION_MODEL
    ):
        raise RuntimeError(
            f"canonical annotation_version {_CANONICAL_PRODUCTION_ANNOTATION_VERSION!r}은 "
            f"provider={_CANONICAL_PRODUCTION_PROVIDER}/model={_CANONICAL_PRODUCTION_MODEL} 전용입니다. "
            f"현재 provider={labeler.provider}, model={labeler.model}로는 사용할 수 없습니다 - "
            "이 run의 provider/model 설정이 의도한 것인지 먼저 확인하세요."
        )
    annotation_version = _CANONICAL_PRODUCTION_ANNOTATION_VERSION
    print(
        f"production LLM provider={labeler.provider} model={labeler.model} annotation_version={annotation_version}"
    )

    span_builder = NiaSourceSpanBuilder()
    provenance = NiaRecordProvenanceIndex()
    processor = NiaPilotRecordProcessor(labeler, span_builder, matching_stage, provenance)
    parser = NiaLabelingParser()

    runner = NiaProductionAnnotationRunner(
        processor,
        parser,
        store,
        _PRODUCTION_FAILURES_PATH,
        _PRODUCTION_REVIEW_SIGNALS_PATH,
        annotation_version,
    )
    await runner.run_many(target_ids, qa_corpus, already_done)

    regenerate_downstream(
        _PRODUCTION_ANNOTATIONS_PATH,
        _PRODUCTION_REVIEW_SIGNALS_PATH,
        _PRODUCTION_REVIEW_QUEUE_PATH,
        _PRODUCTION_CLAIM_INGESTION_PATH,
    )
    final_done = store.load_completed_record_ids(set(qa_corpus.keys()))
    print(f"완료: {len(final_done)}/{len(qa_corpus)}건. 저장: {_PRODUCTION_ANNOTATIONS_PATH}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run())
