import hashlib
import zipfile
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from data.scripts.nia_case_rag.annotation_corpus_exporter import (
    NiaAnnotationCorpusExporter,
    NiaAnnotationCorpusExportError,
    NiaAnnotationCorpusExportErrorCode,
)
from data.scripts.nia_case_rag.annotation_corpus_schemas import (
    NiaAnnotationCorpusExportRequest,
    NiaAnnotationCorpusManifest,
    NiaAnnotationCorpusProvenance,
)
from data.scripts.nia_case_rag.export_schemas import NiaCaseExportRequest
from data.scripts.nia_case_rag.exporter import NiaCaseExporter
from data.scripts.nia_original_schemas import NiaOriginalRecord


class TestNiaAnnotationCorpusExporter:
    def test_case_document와_같은_3581_대상만_raw와_provenance로_내보낸다(
        self, tmp_path: Path
    ) -> None:
        input_root = tmp_path / "dataset"
        self._write_zip(
            input_root / "Training" / "02.라벨링데이터" / "TL_모공.zip",
            [self._record("train-20", 20, "모공"), self._record("train-40", 40, "모공")],
        )
        self._write_zip(
            input_root / "Validation" / "02.라벨링데이터" / "VL_여드름_뾰루지.zip",
            [self._record("valid-30", 30, "여드름/뾰루지")],
        )
        paths = self._create_case_export(tmp_path, input_root)

        result = NiaAnnotationCorpusExporter().export(
            NiaAnnotationCorpusExportRequest(
                input_root=input_root,
                case_documents_path=paths.case_documents,
                output_path=paths.corpus,
                provenance_path=paths.provenance,
                manifest_path=paths.manifest,
            )
        )

        raw_records = [
            NiaOriginalRecord.model_validate_json(line)
            for line in paths.corpus.read_text(encoding="utf-8").splitlines()
        ]
        provenance = [
            NiaAnnotationCorpusProvenance.model_validate_json(line)
            for line in paths.provenance.read_text(encoding="utf-8").splitlines()
        ]
        manifest = NiaAnnotationCorpusManifest.model_validate_json(
            paths.manifest.read_text(encoding="utf-8")
        )
        assert [record.info.id for record in raw_records] == ["train-20", "valid-30"]
        assert [row.record_id for row in provenance] == ["train-20", "valid-30"]
        assert all(not row.archive_mismatch for row in provenance)
        assert manifest.input_record_count == 3
        assert manifest.output_record_count == 2
        assert manifest.training_record_count == 1
        assert manifest.validation_record_count == 1
        assert manifest.corpus_sha256 == hashlib.sha256(paths.corpus.read_bytes()).hexdigest()
        assert (
            manifest.provenance_sha256 == hashlib.sha256(paths.provenance.read_bytes()).hexdigest()
        )
        assert result.manifest == manifest

    def test_case_document와_ID가_다르면_산출물을_게시하지_않는다(self, tmp_path: Path) -> None:
        input_root = tmp_path / "dataset"
        self._write_zip(
            input_root / "Training" / "02.라벨링데이터" / "TL_모공.zip",
            [self._record("case-1", 20, "모공"), self._record("case-2", 21, "모공")],
        )
        paths = self._create_case_export(tmp_path, input_root)
        first_case = paths.case_documents.read_text(encoding="utf-8").splitlines()[0]
        paths.case_documents.write_text(f"{first_case}\n", encoding="utf-8")

        with pytest.raises(NiaAnnotationCorpusExportError) as error:
            NiaAnnotationCorpusExporter().export(
                NiaAnnotationCorpusExportRequest(
                    input_root=input_root,
                    case_documents_path=paths.case_documents,
                    output_path=paths.corpus,
                    provenance_path=paths.provenance,
                    manifest_path=paths.manifest,
                )
            )

        assert error.value.code is NiaAnnotationCorpusExportErrorCode.CASE_ID_MISMATCH
        assert not paths.corpus.exists()
        assert not paths.provenance.exists()
        assert not paths.manifest.exists()

    def _create_case_export(self, tmp_path: Path, input_root: Path) -> "_ExportPaths":
        paths = _ExportPaths(
            case_documents=tmp_path / "case_documents.jsonl",
            case_manifest=tmp_path / "case_documents.manifest.json",
            corpus=tmp_path / "annotation_corpus.jsonl",
            provenance=tmp_path / "annotation_provenance.jsonl",
            manifest=tmp_path / "annotation_manifest.json",
        )
        NiaCaseExporter().export(
            NiaCaseExportRequest(
                input_root=input_root,
                output_path=paths.case_documents,
                manifest_path=paths.case_manifest,
            )
        )
        return paths

    def _record(self, record_id: str, age: int, target_concern: str) -> NiaOriginalRecord:
        return NiaOriginalRecord.model_validate(
            {
                "info": {
                    "id": record_id,
                    "source_survey_id": record_id,
                    "target_concern": target_concern,
                    "question": f"질문 {record_id}",
                    "answer": f"답변 {record_id}",
                    "evidence_sources": [],
                },
                "meta": {
                    "gender": "여성",
                    "age": age,
                    "initial_skin_condition": "상태",
                    "skin_type": "지성",
                    "skin_concerns": [target_concern],
                    "image_filename": f"{record_id}.jpg",
                },
                "external": [],
                "chain_of_thought": [{"step": 1, "title": "분석", "content": f"추론 {record_id}"}],
            }
        )

    def _write_zip(self, path: Path, records: list[NiaOriginalRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(record.model_dump_json() for record in records)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("records.jsonl", f"{text}\n")


class _ExportPaths(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_documents: Path
    case_manifest: Path
    corpus: Path
    provenance: Path
    manifest: Path
