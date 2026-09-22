import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from data.scripts.nia_case_rag.export_schemas import (
    NiaCaseDatasetSplit,
    NiaCaseExportManifest,
    NiaCaseExportRecord,
    NiaCaseExportRequest,
)
from data.scripts.nia_case_rag.exporter import (
    NiaCaseExporter,
    NiaCaseExportError,
    NiaCaseExportErrorCode,
    NiaCaseInputDiscovery,
)
from data.scripts.nia_original_schemas import NiaOriginalRecord


class TestNiaCaseInputDiscovery:
    def test_Training과_Validation의_라벨링_ZIP만_찾는다(self, tmp_path: Path) -> None:
        training = tmp_path / "Training" / "02.라벨링데이터" / "TL_train.zip"
        validation = tmp_path / "Validation" / "02.라벨링데이터" / "VL_valid.zip"
        source = tmp_path / "Training" / "01.원천데이터" / "TS_ignore.zip"
        other = tmp_path / "Other" / "02.기타데이터" / "TL_ignore.zip"
        for path in (training, validation, source, other):
            self._write_empty_zip(path)

        archives = NiaCaseInputDiscovery().discover(tmp_path)

        assert [(archive.path.name, archive.dataset_split) for archive in archives] == [
            ("TL_train.zip", NiaCaseDatasetSplit.TRAINING),
            ("VL_valid.zip", NiaCaseDatasetSplit.VALIDATION),
        ]

    def test_TL_archive가_Validation에_있으면_실패한다(self, tmp_path: Path) -> None:
        invalid = tmp_path / "Validation" / "02.라벨링데이터" / "TL_invalid.zip"
        self._write_empty_zip(invalid)

        with pytest.raises(NiaCaseExportError) as error:
            NiaCaseInputDiscovery().discover(tmp_path)

        assert error.value.code is NiaCaseExportErrorCode.INVALID_ARCHIVE_SPLIT

    @staticmethod
    def _write_empty_zip(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w"):
            pass


class TestNiaCaseExporter:
    def test_기존_세_단계를_조립해_JSONL과_manifest를_생성한다(self, tmp_path: Path) -> None:
        input_root = tmp_path / "dataset"
        self._write_zip(
            input_root / "Training" / "02.라벨링데이터" / "TL_a.zip",
            [
                self._record("train-10", 10),
                self._record("train-39", 39),
                self._record("train-40", 40),
            ],
        )
        self._write_zip(
            input_root / "Validation" / "02.라벨링데이터" / "VL_a.zip",
            [self._record("valid-9", 9), self._record("valid-20", 20)],
        )
        output_path = tmp_path / "out" / "cases.jsonl"
        manifest_path = tmp_path / "out" / "cases.manifest.json"

        result = NiaCaseExporter().export(
            NiaCaseExportRequest(
                input_root=input_root,
                output_path=output_path,
                manifest_path=manifest_path,
            )
        )

        records = [
            NiaCaseExportRecord.model_validate_json(line)
            for line in output_path.read_text(encoding="utf-8").splitlines()
        ]
        manifest = NiaCaseExportManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        assert [record.document.case_id for record in records] == [
            "train-10",
            "train-39",
            "valid-20",
        ]
        assert [record.dataset_split for record in records] == [
            NiaCaseDatasetSplit.TRAINING,
            NiaCaseDatasetSplit.TRAINING,
            NiaCaseDatasetSplit.VALIDATION,
        ]
        assert records[0].source.archive_name == "TL_a.zip"
        assert records[0].source.member_name == "records.jsonl"
        assert records[0].source.line_number == 1
        assert manifest.input_archive_count == 2
        assert manifest.input_record_count == 5
        assert manifest.output_record_count == 3
        assert manifest.training_record_count == 2
        assert manifest.validation_record_count == 1
        assert manifest.output_sha256 == hashlib.sha256(output_path.read_bytes()).hexdigest()
        assert result.manifest == manifest

    def test_같은_case_id가_두_archive에_있으면_결과를_게시하지_않는다(
        self, tmp_path: Path
    ) -> None:
        input_root = tmp_path / "dataset"
        self._write_zip(
            input_root / "Training" / "02.라벨링데이터" / "TL_a.zip",
            [self._record("duplicate", 20)],
        )
        self._write_zip(
            input_root / "Validation" / "02.라벨링데이터" / "VL_a.zip",
            [self._record("duplicate", 30)],
        )
        output_path = tmp_path / "cases.jsonl"
        manifest_path = tmp_path / "cases.manifest.json"

        with pytest.raises(NiaCaseExportError) as error:
            NiaCaseExporter().export(
                NiaCaseExportRequest(
                    input_root=input_root,
                    output_path=output_path,
                    manifest_path=manifest_path,
                )
            )

        assert error.value.code is NiaCaseExportErrorCode.DUPLICATE_CASE_ID
        assert not output_path.exists()
        assert not manifest_path.exists()

    def test_기존_출력은_overwrite_없이_덮어쓰지_않는다(self, tmp_path: Path) -> None:
        input_root = tmp_path / "dataset"
        self._write_zip(
            input_root / "Training" / "02.라벨링데이터" / "TL_a.zip",
            [self._record("case-1", 20)],
        )
        output_path = tmp_path / "cases.jsonl"
        manifest_path = tmp_path / "cases.manifest.json"
        output_path.write_text("preserve", encoding="utf-8")

        with pytest.raises(NiaCaseExportError) as error:
            NiaCaseExporter().export(
                NiaCaseExportRequest(
                    input_root=input_root,
                    output_path=output_path,
                    manifest_path=manifest_path,
                )
            )

        assert error.value.code is NiaCaseExportErrorCode.OUTPUT_ALREADY_EXISTS
        assert output_path.read_text(encoding="utf-8") == "preserve"
        assert not manifest_path.exists()

    @staticmethod
    def _record(case_id: str, age: int) -> NiaOriginalRecord:
        return NiaOriginalRecord.model_validate(
            {
                "info": {
                    "id": case_id,
                    "source_survey_id": case_id,
                    "target_concern": "모공",
                    "question": f"질문 {case_id}",
                    "answer": f"답변 {case_id}",
                    "evidence_sources": [],
                },
                "meta": {
                    "gender": "여성",
                    "age": age,
                    "initial_skin_condition": "상태",
                    "skin_type": "지성",
                    "skin_concerns": ["모공"],
                    "image_filename": f"{case_id}.jpg",
                },
                "external": [],
                "chain_of_thought": [
                    {"step": 1, "title": "분석", "content": f"추론 {case_id}"}
                ],
            }
        )

    @staticmethod
    def _write_zip(path: Path, records: list[NiaOriginalRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False) for record in records
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("records.jsonl", f"{text}\n")
