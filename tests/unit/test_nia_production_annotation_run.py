"""production annotation runner의 incremental persistence/resume/무결성 검사를
LLM/DB 호출 없이 검증한다. 실제 라벨링 로직(processor/matcher/parser)은 전부 재사용하고,
`NiaLlmLabeler`만 record_id -> 미리 정해둔 `LlmNiaLabelingOutput`(혹은 예외)을 돌려주는
가짜로 대체한다.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

import data.scripts.nia_production_annotation_run as run_module
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.ingredient_schemas import IngredientCandidate
from data.scripts.nia_case_rag.annotation_corpus_schemas import (
    NiaAnnotationCorpusArchiveEntry,
    NiaAnnotationCorpusManifest,
)
from data.scripts.nia_case_rag.export_schemas import NiaCaseDatasetSplit
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_labeling_parser import NiaLabelingParser
from data.scripts.nia_llm_label_schemas import (
    LlmCaseObservationStatement,
    LlmIngredientMention,
    LlmNiaLabelingOutput,
    LlmSourceQuote,
    LlmUsageInstructionStatement,
)
from data.scripts.nia_original_schemas import NiaOriginalRecord
from data.scripts.nia_pilot_runner import NiaPilotRecordProcessor
from data.scripts.nia_production_annotation_run import (
    NiaProductionAnnotationApplication,
    NiaProductionAnnotationRequest,
    NiaProductionAnnotationRunner,
    NiaProductionAnnotationStore,
    NiaProductionInputBundle,
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
    tmp_path,
    outcomes: dict[str, LlmNiaLabelingOutput | Exception],
    record_ids: list[str],
    version: str = "llm-production-test",
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
        processor, parser, store, failures_path, review_signals_path, version
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


class TestCanonicalAnnotationVersionStability:
    """회귀 배경: `_PRODUCTION_ANNOTATION_VERSION_PREFIX`가 과거엔
    `datetime.now(UTC).date().isoformat()`로 실행 시점마다 새로 계산됐다. 09-17에 시작한
    production run을 09-18에 재시작(resume)했더니 같은 논리적 run 안에 annotation_version이
    두 종류(09-17 889건, 09-18 608건) 섞여 버렸다. 이제는 날짜와 무관한 고정 상수만 쓴다."""

    def test_annotation_version_is_a_fixed_constant_not_derived_from_wall_clock_date(self) -> None:
        assert not hasattr(run_module, "_PRODUCTION_ANNOTATION_VERSION_PREFIX")
        assert not hasattr(run_module, "datetime")
        assert (
            run_module._CANONICAL_PRODUCTION_ANNOTATION_VERSION
            == "llm-production-2026-09-17-openai-gpt-4o-mini"
        )

    def test_two_run_invocations_across_a_simulated_date_change_share_one_version(
        self, tmp_path
    ) -> None:
        """1번째 실행("09-17")과 재시작 후 이어지는 실행("09-18"으로 날짜가 바뀐 상태를
        흉내)이 서로 다른 runner 인스턴스라도, `_run()`이 실제로 쓰는 canonical 상수를 넘기면
        두 record 모두 완전히 동일한 annotation_version을 가져야 한다."""
        ids = ["REC1", "REC2"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}
        canonical = run_module._CANONICAL_PRODUCTION_ANNOTATION_VERSION

        import asyncio

        runner_day1, store, annotations_path, _, _ = _build_runner(
            tmp_path, outcomes, ids, version=canonical
        )
        asyncio.run(runner_day1.run_many(["REC1"], records, already_done=set()))

        # 재시작 시뮬레이션: 새 runner 인스턴스(=프로세스 재기동)지만 같은 canonical 상수를 쓴다.
        completed = store.load_completed_record_ids(set(ids))
        runner_day2, _store2, annotations_path2, _, _ = _build_runner(
            tmp_path, outcomes, ids, version=canonical
        )
        assert annotations_path2 == annotations_path  # 동일 output 파일에 이어서 씀
        target_ids = [rid for rid in ids if rid not in completed]
        asyncio.run(runner_day2.run_many(target_ids, records, already_done=completed))

        persisted = run_module._read_jsonl(annotations_path)
        versions = {d["annotation_version"] for d in persisted}
        assert versions == {canonical}


class TestExistingOutputResume:
    def test_resume_with_large_existing_output_skips_done_and_appends_with_canonical_version(
        self, tmp_path
    ) -> None:
        """기존 1,497건과 같은 상황을 축소 재현: 이미 완료된 record는 다시 라벨링하지 않고,
        새로 처리되는 record만 append되며, append된 record도 기존과 동일한 canonical
        annotation_version을 가져야 한다."""
        canonical = run_module._CANONICAL_PRODUCTION_ANNOTATION_VERSION
        done_ids = [f"DONE{i}" for i in range(5)]
        new_ids = ["NEW1", "NEW2"]
        all_ids = done_ids + new_ids
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in all_ids}
        outcomes = {
            rid: _case_observation_output(records[rid]["info"]["question"]) for rid in all_ids
        }

        runner, store, annotations_path, _, _ = _build_runner(
            tmp_path, outcomes, all_ids, version=canonical
        )

        import asyncio

        # 기존 5건은 이미 완료된 상태를 미리 만들어 둔다.
        asyncio.run(runner.run_many(done_ids, records, already_done=set()))
        completed_before = store.load_completed_record_ids(set(all_ids))
        assert completed_before == set(done_ids)

        # resume: 새 2건만 대상이어야 한다.
        target_ids = [rid for rid in all_ids if rid not in completed_before]
        assert target_ids == new_ids
        asyncio.run(runner.run_many(target_ids, records, already_done=completed_before))

        persisted = run_module._read_jsonl(annotations_path)
        assert {d["source"]["record_id"] for d in persisted} == set(all_ids)
        assert {d["annotation_version"] for d in persisted} == {canonical}


class TestMixedVersionDetection:
    def test_load_completed_record_ids_fails_fast_on_mixed_versions(self, tmp_path) -> None:
        """같은 production output 파일에 서로 다른 annotation_version이 섞여 있으면(이번
        회귀의 실제 증상) silent continue하지 말고 즉시 실패해야 한다."""
        ids = ["REC1", "REC2"]
        records = {rid: _record(rid, f"{rid} 텍스트 내용입니다.") for rid in ids}
        outcomes = {rid: _case_observation_output(records[rid]["info"]["question"]) for rid in ids}

        import asyncio

        runner_a, store, annotations_path, _, _ = _build_runner(
            tmp_path, outcomes, ids, version="llm-production-2026-09-17-openai-gpt-4o-mini"
        )
        asyncio.run(runner_a.run_one("REC1", records["REC1"], already_done=set()))

        runner_b, _store_b, annotations_path_b, _, _ = _build_runner(
            tmp_path, outcomes, ids, version="llm-production-2026-09-18-openai-gpt-4o-mini"
        )
        assert annotations_path_b == annotations_path  # 같은 파일에 append됨
        asyncio.run(runner_b.run_one("REC2", records["REC2"], already_done=set()))

        with pytest.raises(NiaProductionOutputIntegrityError, match="annotation_version이 섞여"):
            store.load_completed_record_ids(set(ids))


class TestSafeProductionRunSelection:
    def test_제한_없는_실행은_명시적_승인_없이는_거부한다(self) -> None:
        with pytest.raises(ValidationError, match="approve-full-run"):
            NiaProductionAnnotationRequest()

    def test_dry_run과_limit은_전체_실행_승인_없이_허용한다(self) -> None:
        assert NiaProductionAnnotationRequest(dry_run=True).dry_run
        assert NiaProductionAnnotationRequest(limit=5).limit == 5

    def test_limit과_record_id는_동시에_선택할_수_없다(self) -> None:
        with pytest.raises(ValidationError, match="동시에 사용할 수 없습니다"):
            NiaProductionAnnotationRequest(limit=1, record_ids=("REC1",))

    def test_dry_run_limit은_입력_순서의_미완료_건만_선택한다(self, tmp_path) -> None:
        record_ids = ["REC1", "REC2", "REC3"]
        provenance = NiaRecordProvenanceIndex(audit_path=_write_audit_file(tmp_path, record_ids))
        bundle = NiaProductionInputBundle(
            records={record_id: self._valid_record(record_id) for record_id in record_ids},
            provenance=provenance,
            manifest=NiaAnnotationCorpusManifest(
                input_archive_count=1,
                input_record_count=3,
                output_record_count=3,
                training_record_count=3,
                validation_record_count=0,
                archives=[
                    NiaAnnotationCorpusArchiveEntry(
                        archive_name="TL_test.zip",
                        dataset_split=NiaCaseDatasetSplit.TRAINING,
                        input_record_count=3,
                        output_record_count=3,
                    )
                ],
                corpus_sha256="0" * 64,
                provenance_sha256="0" * 64,
                case_documents_sha256="0" * 64,
            ),
        )
        application = NiaProductionAnnotationApplication(reader=_FakeInputReader(bundle))

        prepared = application.prepare(
            NiaProductionAnnotationRequest(
                annotations_path=tmp_path / "annotations.jsonl",
                dry_run=True,
                limit=2,
            )
        )

        assert prepared.plan.selected_record_ids == ["REC1", "REC2"]
        assert prepared.plan.pending_count == 3

    def _valid_record(self, record_id: str) -> NiaOriginalRecord:
        return NiaOriginalRecord.model_validate(
            {
                "info": {
                    "id": record_id,
                    "source_survey_id": record_id,
                    "target_concern": "모공",
                    "question": f"질문 {record_id}",
                    "answer": f"답변 {record_id}",
                    "evidence_sources": [],
                },
                "meta": {
                    "gender": "여성",
                    "age": 20,
                    "initial_skin_condition": "상태",
                    "skin_type": "지성",
                    "skin_concerns": ["모공"],
                    "image_filename": f"{record_id}.jpg",
                },
                "external": [],
                "chain_of_thought": [{"step": 1, "title": "분석", "content": f"추론 {record_id}"}],
            }
        )


class _FakeInputReader:
    def __init__(self, bundle: NiaProductionInputBundle) -> None:
        self._bundle = bundle

    def read(self, request: NiaProductionAnnotationRequest) -> NiaProductionInputBundle:
        return self._bundle
