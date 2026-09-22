"""AI Hub 원본에서 production Claim annotation 입력 corpus를 만든다.

LLM을 호출하지 않으며, 같은 원본에서 만든 NIA Case Document와 ID 집합이 정확히 같을 때만
산출물을 게시한다.
"""

import argparse
import hashlib
import io
import json
import sys
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from data.scripts.nia_case_rag.annotation_corpus_schemas import (
    NiaAnnotationCorpusArchiveEntry,
    NiaAnnotationCorpusExportRequest,
    NiaAnnotationCorpusExportResult,
    NiaAnnotationCorpusManifest,
    NiaAnnotationCorpusProvenance,
)
from data.scripts.nia_case_rag.export_schemas import (
    NiaCaseDatasetSplit,
    NiaCaseExportRecord,
    NiaCaseInputArchive,
)
from data.scripts.nia_case_rag.exporter import NiaCaseInputDiscovery
from data.scripts.nia_original_age_filter import NiaOriginalAgeFilter
from data.scripts.nia_original_loader import NiaOriginalLoader
from data.scripts.nia_original_schemas import NiaOriginalEntry

DEFAULT_OUTPUT_PATH = Path("data/processed/nia_qa_10s_30s.jsonl")
DEFAULT_PROVENANCE_PATH = Path("data/processed/nia_qa_10s_30s.provenance.jsonl")
DEFAULT_MANIFEST_PATH = Path("data/processed/nia_qa_10s_30s.manifest.json")
DEFAULT_CASE_DOCUMENTS_PATH = Path("data/processed/nia_case_documents_10s_30s.jsonl")
SHA256_READ_SIZE_BYTES = 1024 * 1024


class NiaAnnotationCorpusExportErrorCode(StrEnum):
    CASE_DOCUMENTS_NOT_FOUND = "case_documents_not_found"
    INVALID_CASE_DOCUMENT = "invalid_case_document"
    DUPLICATE_CASE_ID = "duplicate_case_id"
    DUPLICATE_RECORD_ID = "duplicate_record_id"
    CASE_ID_MISMATCH = "case_id_mismatch"
    OUTPUT_ALREADY_EXISTS = "output_already_exists"


class NiaAnnotationCorpusExportError(RuntimeError):
    def __init__(self, code: NiaAnnotationCorpusExportErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"NIA annotation corpus export 실패 [{code.value}]: {message}")


class NiaAnnotationCorpusExporter:
    def __init__(
        self,
        discovery: NiaCaseInputDiscovery | None = None,
        loader: NiaOriginalLoader | None = None,
        age_filter: NiaOriginalAgeFilter | None = None,
    ) -> None:
        self._discovery = discovery or NiaCaseInputDiscovery()
        self._loader = loader or NiaOriginalLoader()
        self._age_filter = age_filter or NiaOriginalAgeFilter()

    def export(self, request: NiaAnnotationCorpusExportRequest) -> NiaAnnotationCorpusExportResult:
        case_ids = self._read_case_ids(request.case_documents_path)
        archives = self._discovery.discover(request.input_root)
        self._prepare_destinations(request)
        corpus_temp = self._temporary_path(request.output_path)
        provenance_temp = self._temporary_path(request.provenance_path)
        manifest_temp = self._temporary_path(request.manifest_path)

        try:
            manifest = self._write_exports(
                corpus_temp,
                provenance_temp,
                request.case_documents_path,
                case_ids,
                archives,
            )
            self._write_manifest(manifest_temp, manifest)
            self._publish(request, corpus_temp, provenance_temp, manifest_temp)
        except (OSError, RuntimeError, ValueError):
            corpus_temp.unlink(missing_ok=True)
            provenance_temp.unlink(missing_ok=True)
            manifest_temp.unlink(missing_ok=True)
            raise

        return NiaAnnotationCorpusExportResult(
            output_path=request.output_path,
            provenance_path=request.provenance_path,
            manifest_path=request.manifest_path,
            manifest=manifest,
        )

    def _read_case_ids(self, path: Path) -> set[str]:
        if not path.is_file():
            raise NiaAnnotationCorpusExportError(
                NiaAnnotationCorpusExportErrorCode.CASE_DOCUMENTS_NOT_FOUND,
                f"NIA Case Document JSONL이 없습니다: {path}",
            )
        case_ids: set[str] = set()
        with path.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                try:
                    record = NiaCaseExportRecord.model_validate_json(line)
                except ValidationError as exc:
                    raise NiaAnnotationCorpusExportError(
                        NiaAnnotationCorpusExportErrorCode.INVALID_CASE_DOCUMENT,
                        f"Case Document 파싱 실패: {path}:{line_number}: {exc}",
                    ) from exc
                case_id = record.document.case_id
                if case_id in case_ids:
                    raise NiaAnnotationCorpusExportError(
                        NiaAnnotationCorpusExportErrorCode.DUPLICATE_CASE_ID,
                        f"Case Document에 중복 case_id가 있습니다: {case_id}",
                    )
                case_ids.add(case_id)
        return case_ids

    def _prepare_destinations(self, request: NiaAnnotationCorpusExportRequest) -> None:
        destinations = [request.output_path, request.provenance_path, request.manifest_path]
        existing = [path for path in destinations if path.exists()]
        if existing and not request.overwrite:
            joined = ", ".join(str(path) for path in existing)
            raise NiaAnnotationCorpusExportError(
                NiaAnnotationCorpusExportErrorCode.OUTPUT_ALREADY_EXISTS,
                f"기존 산출물을 보존하기 위해 중단했습니다: {joined}. --overwrite가 필요합니다.",
            )
        for path in destinations:
            path.parent.mkdir(parents=True, exist_ok=True)

    def _temporary_path(self, destination: Path) -> Path:
        return destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")

    def _write_exports(
        self,
        corpus_path: Path,
        provenance_path: Path,
        case_documents_path: Path,
        expected_case_ids: set[str],
        archives: list[NiaCaseInputArchive],
    ) -> NiaAnnotationCorpusManifest:
        record_ids: set[str] = set()
        archive_entries: list[NiaAnnotationCorpusArchiveEntry] = []
        training_count = 0
        validation_count = 0

        with (
            corpus_path.open("x", encoding="utf-8", newline="\n") as corpus_file,
            provenance_path.open("x", encoding="utf-8", newline="\n") as provenance_file,
        ):
            for archive in archives:
                entries = list(self._loader.iter_entries([archive.path]))
                output_count = 0
                for entry in self._age_filter.filter(entries):
                    record_id = entry.record.info.id
                    if record_id in record_ids:
                        raise NiaAnnotationCorpusExportError(
                            NiaAnnotationCorpusExportErrorCode.DUPLICATE_RECORD_ID,
                            f"10~39세 corpus에 중복 record_id가 있습니다: {record_id}",
                        )
                    record_ids.add(record_id)
                    corpus_file.write(entry.record.model_dump_json())
                    corpus_file.write("\n")
                    provenance = self._to_provenance(archive, entry)
                    provenance_file.write(provenance.model_dump_json())
                    provenance_file.write("\n")
                    output_count += 1

                archive_entries.append(
                    NiaAnnotationCorpusArchiveEntry(
                        archive_name=archive.path.name,
                        dataset_split=archive.dataset_split,
                        input_record_count=len(entries),
                        output_record_count=output_count,
                    )
                )
                if archive.dataset_split is NiaCaseDatasetSplit.TRAINING:
                    training_count += output_count
                else:
                    validation_count += output_count

        missing_ids = expected_case_ids - record_ids
        extra_ids = record_ids - expected_case_ids
        if missing_ids or extra_ids:
            raise NiaAnnotationCorpusExportError(
                NiaAnnotationCorpusExportErrorCode.CASE_ID_MISMATCH,
                "Case Document와 annotation corpus의 ID 집합이 다릅니다: "
                f"missing={len(missing_ids)}, extra={len(extra_ids)}, "
                f"missing_sample={sorted(missing_ids)[:5]}, extra_sample={sorted(extra_ids)[:5]}",
            )

        return NiaAnnotationCorpusManifest(
            input_archive_count=len(archives),
            input_record_count=sum(item.input_record_count for item in archive_entries),
            output_record_count=len(record_ids),
            training_record_count=training_count,
            validation_record_count=validation_count,
            duplicate_record_id_count=0,
            missing_case_id_count=0,
            extra_case_id_count=0,
            archives=archive_entries,
            corpus_sha256=self._sha256(corpus_path),
            provenance_sha256=self._sha256(provenance_path),
            case_documents_sha256=self._sha256(case_documents_path),
        )

    def _to_provenance(
        self, archive: NiaCaseInputArchive, entry: NiaOriginalEntry
    ) -> NiaAnnotationCorpusProvenance:
        target_concern = entry.record.info.target_concern
        archive_target = archive.path.stem[3:].replace("_", "/")
        return NiaAnnotationCorpusProvenance(
            record_id=entry.record.info.id,
            dataset_split=archive.dataset_split,
            source_archive=archive.path.name,
            source_member=entry.source.member_name,
            source_line_number=entry.source.line_number,
            info_target_concern=target_concern,
            archive_mismatch=archive_target != target_concern,
        )

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as input_file:
            while chunk := input_file.read(SHA256_READ_SIZE_BYTES):
                digest.update(chunk)
        return digest.hexdigest()

    def _write_manifest(self, path: Path, manifest: NiaAnnotationCorpusManifest) -> None:
        serialized = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
        path.write_text(f"{serialized}\n", encoding="utf-8", newline="\n")

    def _publish(
        self,
        request: NiaAnnotationCorpusExportRequest,
        corpus_temp: Path,
        provenance_temp: Path,
        manifest_temp: Path,
    ) -> None:
        if not request.overwrite:
            for destination in (
                request.output_path,
                request.provenance_path,
                request.manifest_path,
            ):
                if destination.exists():
                    raise NiaAnnotationCorpusExportError(
                        NiaAnnotationCorpusExportErrorCode.OUTPUT_ALREADY_EXISTS,
                        f"export 도중 대상 파일이 생성되어 덮어쓰지 않았습니다: {destination}",
                    )
        corpus_temp.replace(request.output_path)
        provenance_temp.replace(request.provenance_path)
        manifest_temp.replace(request.manifest_path)


class NiaAnnotationCorpusExportCli:
    def run(self, argv: Sequence[str] | None = None) -> int:
        self._configure_stdout()
        arguments = self._parser().parse_args(argv)
        result = NiaAnnotationCorpusExporter().export(
            NiaAnnotationCorpusExportRequest(
                input_root=arguments.input_root,
                case_documents_path=arguments.case_documents,
                output_path=arguments.output,
                provenance_path=arguments.provenance,
                manifest_path=arguments.manifest,
                overwrite=arguments.overwrite,
            )
        )
        self._print_result(result)
        return 0

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="NIA production annotation 입력 corpus를 Case Document와 대조해 생성합니다.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        parser.add_argument("--input-root", type=Path, required=True)
        parser.add_argument("--case-documents", type=Path, default=DEFAULT_CASE_DOCUMENTS_PATH)
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
        parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE_PATH)
        parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
        parser.add_argument("--overwrite", action="store_true")
        return parser

    def _configure_stdout(self) -> None:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def _print_result(self, result: NiaAnnotationCorpusExportResult) -> None:
        manifest = result.manifest
        print("NIA production annotation corpus export 완료")
        print(
            f"- 출력: {manifest.output_record_count:,}건 "
            f"(training {manifest.training_record_count:,}, validation {manifest.validation_record_count:,})"
        )
        print("- Case Document ID 대조: 일치")
        print(f"- corpus: {result.output_path}")
        print(f"- provenance: {result.provenance_path}")
        print(f"- manifest: {result.manifest_path}")


if __name__ == "__main__":
    raise SystemExit(NiaAnnotationCorpusExportCli().run())
