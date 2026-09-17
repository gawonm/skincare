"""production annotation runner의 incremental persistence/resume/무결성 검사를
LLM/DB 호출 없이 검증한다. 실제 라벨링 로직(processor/matcher/parser)은 전부 재사용하고,
`NiaLlmLabeler`만 record_id -> 미리 정해둔 `LlmNiaLabelingOutput`(혹은 예외)을 돌려주는
가짜로 대체한다.
"""

from uuid import uuid4

import pytest

import data.scripts.nia_production_annotation_run as run_module
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.ingredient_schemas import IngredientCandidate
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_labeling_parser import NiaLabelingParser
from data.scripts.nia_llm_label_schemas import (
    LlmCaseObservationStatement,
    LlmIngredientMention,
    LlmNiaLabelingOutput,
    LlmSourceQuote,
    LlmUsageInstructionStatement,
)
from data.scripts.nia_pilot_runner import NiaPilotRecordProcessor
from data.scripts.nia_production_annotation_run import (
    NiaProductionAnnotationRunner,
    NiaProductionAnnotationStore,
    NiaProductionOutputIntegrityError,
    regenerate_downstream,
)
from data.scripts.nia_record_provenance import NiaRecordProvenanceIndex
from data.scripts.nia_source_span_builder import NiaSourceSpanBuilder

_NIACINAMIDE_ID = uuid4()


class _FakeLabeler:
    """record_id -> LlmNiaLabelingOutput(또는 예외)만 돌려준다. 실제 LLM 호출 없음."""

    def __init__(self, outcomes: dict[str, LlmNiaLabelingOutput | Exception]) -> None:
        self._outcomes = outcomes
        self.provider = "openai"
        self.model = "gpt-4o-mini-test"
        self.base_url = None

    async def label(self, record: dict) -> LlmNiaLabelingOutput:
        outcome = self._outcomes[record["info"]["id"]]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _record(record_id: str, text: str) -> dict:
    return {
        "info": {"id": record_id, "question": text},
        "meta": {},
        "chain_of_thought": [{"content": text}],
        "external": [],
    }


def _case_observation_output(text: str) -> LlmNiaLabelingOutput:
    return LlmNiaLabelingOutput(
        statements=[
            LlmCaseObservationStatement(
                subject=text,
                quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
            )
        ]
    )


def _write_audit_file(tmp_path, record_ids: list[str]):
    audit_path = tmp_path / "audit.jsonl"
    import json

    with audit_path.open("w", encoding="utf-8") as f:
        for rid in record_ids:
            f.write(
                json.dumps(
                    {
                        "record_id": rid,
                        "dataset_split": "training",
                        "source_archive": "test.zip",
                        "info_target_concern": "test",
                        "archive_mismatch": False,
                        "risk_level": "LOW",
                        "review_reasons": [],
                    }
                )
                + "\n"
            )
    return audit_path


@pytest.fixture(autouse=True)
def _isolate_parser_scratch_files(tmp_path, monkeypatch):
    """실제 repo의 data/processed/ 를 건드리지 않도록 scratch 경로를 tmp_path로 돌린다."""
    monkeypatch.setattr(run_module, "_PARSER_SCRATCH_DOC_PATH", tmp_path / "scratch_doc.json")
    monkeypatch.setattr(run_module, "_PARSER_SCRATCH_RECORD_PATH", tmp_path / "scratch_record.json")


def _build_runner(
    tmp_path, outcomes: dict[str, LlmNiaLabelingOutput | Exception], record_ids: list[str]
):
    labeler = _FakeLabeler(outcomes)
    matching_stage = NiaIngredientMatchingStage(
        IngredientNameMatcher([], IngredientNameNormalizer())
    )
    provenance = NiaRecordProvenanceIndex(audit_path=_write_audit_file(tmp_path, record_ids))
    processor = NiaPilotRecordProcessor(labeler, NiaSourceSpanBuilder(), matching_stage, provenance)
    parser = NiaLabelingParser()
    annotations_path = tmp_path / "annotations.jsonl"
    failures_path = tmp_path / "failures.jsonl"
    review_signals_path = tmp_path / "review_signals.jsonl"
    store = NiaProductionAnnotationStore(annotations_path)
    runner = NiaProductionAnnotationRunner(
        processor, parser, store, failures_path, review_signals_path, "llm-production-test"
    )
    return runner, store, annotations_path, failures_path, review_signals_path


class TestIncrementalPersistenceAndResume:
    def test_a_each_success_is_persisted_immediately(self, tmp_path) -> None:
        """A: 3건 중 2건만 처리하는 상황(=2번째 이후 중단을 시뮬레이션)에서도
        먼저 성공한 record는 이미 디스크에 남아 있어야 한다."""
        ids = ["REC1", "REC2", "REC3"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}
        runner, _store, annotations_path, _, _ = _build_runner(tmp_path, outcomes, ids)

        import asyncio

        # REC3는 아예 시도하지 않는다 - "그 전에 프로세스가 죽었다"와 동일한 상황.
        asyncio.run(runner.run_many(["REC1", "REC2"], records, already_done=set()))

        persisted = run_module._read_jsonl(annotations_path)
        persisted_ids = {d["source"]["record_id"] for d in persisted}
        assert persisted_ids == {"REC1", "REC2"}

    def test_b_resume_only_processes_remaining_records(self, tmp_path) -> None:
        """B: 재실행 시 이미 출력에 있는 record는 다시 호출하지 않고 나머지만 처리한다."""
        ids = ["REC1", "REC2", "REC3"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}
        runner, store, annotations_path, _, _ = _build_runner(tmp_path, outcomes, ids)

        import asyncio

        asyncio.run(runner.run_many(["REC1"], records, already_done=set()))

        completed = store.load_completed_record_ids(set(ids))
        assert completed == {"REC1"}
        target_ids = [rid for rid in ids if rid not in completed]
        assert target_ids == ["REC2", "REC3"]

        asyncio.run(runner.run_many(target_ids, records, already_done=completed))
        final_ids = {d["source"]["record_id"] for d in run_module._read_jsonl(annotations_path)}
        assert final_ids == {"REC1", "REC2", "REC3"}

    def test_c_stale_checkpoint_style_claim_is_ignored(self, tmp_path) -> None:
        """C: 다른 어딘가(예: 예전 pilot checkpoint)가 REC2를 "완료"라고 주장해도,
        production annotation 출력 파일에 실제로 없으면 완료로 인정하지 않는다."""
        ids = ["REC1", "REC2", "REC3"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}
        runner, store, _annotations_path, _, _ = _build_runner(tmp_path, outcomes, ids)

        import asyncio

        asyncio.run(runner.run_many(["REC1"], records, already_done=set()))

        stale_checkpoint_claims = {"REC1", "REC2"}  # REC2는 checkpoint만 주장, 출력엔 없음
        completed = store.load_completed_record_ids(set(ids))  # authoritative source는 이것뿐
        assert "REC2" not in completed
        target_ids = [rid for rid in ids if rid not in completed]
        assert "REC2" in target_ids  # 체크포인트 주장과 무관하게 다시 처리 대상이어야 함
        assert stale_checkpoint_claims != completed  # 체크포인트를 신뢰하지 않았음을 대조 확인

    def test_d_resume_does_not_create_duplicate_lines(self, tmp_path) -> None:
        """D: 이미 완료된 record는 run_one을 직접 불러도(방어적 가드) 중복 기록되지 않는다."""
        ids = ["REC1"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}
        runner, store, annotations_path, _, _ = _build_runner(tmp_path, outcomes, ids)

        import asyncio

        asyncio.run(runner.run_one("REC1", records["REC1"], already_done=set()))
        completed = store.load_completed_record_ids(set(ids))
        status = asyncio.run(runner.run_one("REC1", records["REC1"], already_done=completed))

        assert status == "skipped_already_done"
        persisted = run_module._read_jsonl(annotations_path)
        assert len(persisted) == 1  # 두 번째 호출로 중복 라인이 생기지 않음

    def test_e_one_failure_does_not_block_the_next_record(self, tmp_path) -> None:
        """E: 한 record가 실패해도 다음 record는 정상 처리된다."""
        ids = ["REC1", "REC2"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {
            "REC1": RuntimeError("가짜 LLM 실패"),
            "REC2": _case_observation_output(records["REC2"]["info"]["question"]),
        }
        runner, _store, annotations_path, failures_path, _ = _build_runner(tmp_path, outcomes, ids)

        import asyncio

        asyncio.run(runner.run_many(ids, records, already_done=set()))

        failures = run_module._read_jsonl(failures_path)
        assert [f["record_id"] for f in failures] == ["REC1"]
        persisted_ids = {d["source"]["record_id"] for d in run_module._read_jsonl(annotations_path)}
        assert persisted_ids == {"REC2"}


class TestIntegrityChecks:
    def test_corrupt_line_fails_fast(self, tmp_path) -> None:
        annotations_path = tmp_path / "annotations.jsonl"
        annotations_path.write_text("{not valid json\n", encoding="utf-8")
        store = NiaProductionAnnotationStore(annotations_path)
        with pytest.raises(NiaProductionOutputIntegrityError, match="파싱 실패"):
            store.load_completed_record_ids({"REC1"})

    def test_record_id_not_in_corpus_fails_fast(self, tmp_path) -> None:
        ids = ["REC1"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}
        runner, store, _annotations_path, _, _ = _build_runner(tmp_path, outcomes, ids)

        import asyncio

        asyncio.run(runner.run_many(ids, records, already_done=set()))

        with pytest.raises(NiaProductionOutputIntegrityError, match="input corpus"):
            store.load_completed_record_ids({"REC_OTHER"})  # REC1은 이 "corpus"엔 없음


class TestRegressionUsageInstructionLinkageUnaffected:
    def test_f_usage_instruction_ingredient_linkage_still_works_through_production_wrapper(
        self, tmp_path
    ) -> None:
        text = "나이아신아마이드 세럼을 매일 사용한다."
        record_id = "REC1"
        record = _record(record_id, text)
        stmt = LlmUsageInstructionStatement(
            action_id="A001",
            action=text,
            ingredient_mentions=[
                LlmIngredientMention(raw_name="Niacinamide", raw_name_ko="나이아신아마이드")
            ],
            quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
        )
        labeler = _FakeLabeler({record_id: LlmNiaLabelingOutput(statements=[stmt])})
        candidates = [
            IngredientCandidate(
                ingredient_id=_NIACINAMIDE_ID,
                standard_name_ko="나이아신아마이드",
                standard_name_en="Niacinamide",
                old_names_ko=(),
                old_names_en=(),
                normalized_name_ko="나이아신아마이드",
                normalized_name_en="niacinamide",
            )
        ]
        matching_stage = NiaIngredientMatchingStage(
            IngredientNameMatcher(candidates, IngredientNameNormalizer())
        )
        provenance = NiaRecordProvenanceIndex(audit_path=_write_audit_file(tmp_path, [record_id]))
        processor = NiaPilotRecordProcessor(
            labeler, NiaSourceSpanBuilder(), matching_stage, provenance
        )
        parser = NiaLabelingParser()
        annotations_path = tmp_path / "annotations.jsonl"
        store = NiaProductionAnnotationStore(annotations_path)
        runner = NiaProductionAnnotationRunner(
            processor,
            parser,
            store,
            tmp_path / "failures.jsonl",
            tmp_path / "signals.jsonl",
            "llm-production-test",
        )

        import asyncio

        asyncio.run(runner.run_one(record_id, record, already_done=set()))

        persisted = run_module._read_jsonl(annotations_path)
        assert len(persisted) == 1
        usage_stmt = persisted[0]["statements"][0]
        assert usage_stmt["ingredient_ids"] == [str(_NIACINAMIDE_ID)]
        assert persisted[0]["annotation_version"] == "llm-production-test"


class TestRegenerateDownstream:
    def test_review_queue_and_claim_ingestion_regenerated_from_annotations_only(
        self, tmp_path
    ) -> None:
        ids = ["REC1", "REC2"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}
        runner, _store, annotations_path, _, review_signals_path = _build_runner(
            tmp_path, outcomes, ids
        )

        import asyncio

        asyncio.run(runner.run_many(ids, records, already_done=set()))

        review_queue_path = tmp_path / "review_queue.jsonl"
        claim_ingestion_path = tmp_path / "claim_ingestion.jsonl"
        regenerate_downstream(
            annotations_path, review_signals_path, review_queue_path, claim_ingestion_path
        )

        claim_ingestion = run_module._read_jsonl(claim_ingestion_path)
        assert {row["record_id"] for row in claim_ingestion} == {"REC1", "REC2"}
        assert all(row["statement_type"] == "case_observation" for row in claim_ingestion)

        # 다시 돌려도(재실행 시나리오) 완전히 같은 결과로 덮어써야 한다(결정적).
        regenerate_downstream(
            annotations_path, review_signals_path, review_queue_path, claim_ingestion_path
        )
        claim_ingestion_2 = run_module._read_jsonl(claim_ingestion_path)
        assert claim_ingestion == claim_ingestion_2
