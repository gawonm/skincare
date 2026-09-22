"""AI Hub Q-CoT-A 원본에서 10~39세 NIA Case Document JSONL을 생성한다.

기존 Loader/Filter/Builder를 조립하는 실행 진입점이다. 임베딩, DB 적재, Claim annotation은
수행하지 않는다.

사용 예:
    uv run python -m data.scripts.nia_case_rag.exporter \
      --input-root "C:\\Users\\Admin\\Documents\\03.스킨케어 성분-효능 추천 데이터"
"""

import argparse
import hashlib
import io
import json
import sys
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from data.scripts.nia_case_document_builder import TEXT_VERSION, NiaCaseDocumentBuilder
from data.scripts.nia_case_rag.export_schemas import (
    NiaCaseArchiveManifestEntry,
    NiaCaseDatasetSplit,
    NiaCaseExportManifest,
    NiaCaseExportRecord,
    NiaCaseExportRequest,
    NiaCaseExportResult,
    NiaCaseInputArchive,
    NiaCaseSource,
)
from data.scripts.nia_original_age_filter import NiaOriginalAgeFilter
from data.scripts.nia_original_loader import NiaOriginalLoader

DEFAULT_OUTPUT_PATH = Path("data/processed/nia_case_documents_10s_30s.jsonl")
DEFAULT_MANIFEST_PATH = Path("data/processed/nia_case_documents_10s_30s.manifest.json")
SHA256_READ_SIZE_BYTES = 1024 * 1024


class NiaCaseExportErrorCode(StrEnum):
    INPUT_ROOT_NOT_FOUND = "input_root_not_found"
    INPUT_ARCHIVE_NOT_FOUND = "input_archive_not_found"
    INVALID_ARCHIVE_SPLIT = "invalid_archive_split"
    DUPLICATE_ARCHIVE_NAME = "duplicate_archive_name"
    DUPLICATE_CASE_ID = "duplicate_case_id"
    OUTPUT_ALREADY_EXISTS = "output_already_exists"
    TEMPORARY_OUTPUT_EXISTS = "temporary_output_exists"
    TEXT_VERSION_MISMATCH = "text_version_mismatch"


class NiaCaseExportError(RuntimeError):
    def __init__(self, code: NiaCaseExportErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"NIA Case export 실패 [{code.value}]: {message}")


class NiaCaseInputDiscovery:
    """AI Hub 배포 폴더에서 Training/Validation 라벨링 ZIP만 결정적으로 찾는다."""

    _LABELING_DIRECTORY_NAME: ClassVar[str] = "02.라벨링데이터"
    _TRAINING_DIRECTORY_NAME: ClassVar[str] = "Training"
    _VALIDATION_DIRECTORY_NAME: ClassVar[str] = "Validation"
    _TRAINING_PREFIX: ClassVar[str] = "TL_"
    _VALIDATION_PREFIX: ClassVar[str] = "VL_"
    _SPLIT_ORDER: ClassVar[dict[NiaCaseDatasetSplit, int]] = {
        NiaCaseDatasetSplit.TRAINING: 0,
        NiaCaseDatasetSplit.VALIDATION: 1,
    }

    def discover(self, input_root: Path) -> list[NiaCaseInputArchive]:
        if not input_root.is_dir():
            raise NiaCaseExportError(
                NiaCaseExportErrorCode.INPUT_ROOT_NOT_FOUND,
                f"입력 폴더가 없거나 디렉터리가 아닙니다: {input_root}",
            )

        archives: list[NiaCaseInputArchive] = []
        archive_names: set[str] = set()
        for path in input_root.rglob("*.zip"):
            dataset_split = self._classify(path)
            if dataset_split is None:
                continue
            if path.name in archive_names:
                raise NiaCaseExportError(
                    NiaCaseExportErrorCode.DUPLICATE_ARCHIVE_NAME,
                    f"서로 다른 입력에서 같은 archive 파일명이 발견됐습니다: {path.name}",
                )
            archive_names.add(path.name)
            archives.append(NiaCaseInputArchive(path=path, dataset_split=dataset_split))

        if not archives:
            raise NiaCaseExportError(
                NiaCaseExportErrorCode.INPUT_ARCHIVE_NOT_FOUND,
                f"Training/Validation의 02.라벨링데이터에서 TL_/VL_ ZIP을 찾지 못했습니다: {input_root}",
            )
        return sorted(
            archives,
            key=lambda archive: (
                self._SPLIT_ORDER[archive.dataset_split],
                archive.path.as_posix().casefold(),
            ),
        )

    def _classify(self, path: Path) -> NiaCaseDatasetSplit | None:
        if self._LABELING_DIRECTORY_NAME not in path.parts:
            return None
        if path.name.startswith(self._TRAINING_PREFIX):
            if self._TRAINING_DIRECTORY_NAME not in path.parts:
                raise NiaCaseExportError(
                    NiaCaseExportErrorCode.INVALID_ARCHIVE_SPLIT,
                    f"TL_ archive가 Training 폴더 밖에 있습니다: {path}",
                )
            return NiaCaseDatasetSplit.TRAINING
        if path.name.startswith(self._VALIDATION_PREFIX):
            if self._VALIDATION_DIRECTORY_NAME not in path.parts:
                raise NiaCaseExportError(
                    NiaCaseExportErrorCode.INVALID_ARCHIVE_SPLIT,
                    f"VL_ archive가 Validation 폴더 밖에 있습니다: {path}",
                )
            return NiaCaseDatasetSplit.VALIDATION
        return None


class NiaCaseExporter:
    def __init__(
        self,
        discovery: NiaCaseInputDiscovery | None = None,
        loader: NiaOriginalLoader | None = None,
        age_filter: NiaOriginalAgeFilter | None = None,
        builder: NiaCaseDocumentBuilder | None = None,
    ) -> None:
        self._discovery = discovery or NiaCaseInputDiscovery()
        self._loader = loader or NiaOriginalLoader()
        self._age_filter = age_filter or NiaOriginalAgeFilter()
        self._builder = builder or NiaCaseDocumentBuilder()

    def export(self, request: NiaCaseExportRequest) -> NiaCaseExportResult:
        archives = self._discovery.discover(request.input_root)
        self._prepare_destinations(request)
        output_temp_path = self._temporary_path(request.output_path)
        manifest_temp_path = self._temporary_path(request.manifest_path)

        try:
            manifest = self._write_export(output_temp_path, archives)
            final_manifest = manifest.model_copy(
                update={"output_sha256": self._sha256(output_temp_path)}
            )
            self._write_manifest(manifest_temp_path, final_manifest)
            self._publish(request, output_temp_path, manifest_temp_path)
        except (OSError, RuntimeError, ValueError):
            output_temp_path.unlink(missing_ok=True)
            manifest_temp_path.unlink(missing_ok=True)
            raise

        return NiaCaseExportResult(
            output_path=request.output_path,
            manifest_path=request.manifest_path,
            manifest=final_manifest,
        )

    def _prepare_destinations(self, request: NiaCaseExportRequest) -> None:
        existing = [
            path for path in (request.output_path, request.manifest_path) if path.exists()
        ]
        if existing and not request.overwrite:
            joined = ", ".join(str(path) for path in existing)
            raise NiaCaseExportError(
                NiaCaseExportErrorCode.OUTPUT_ALREADY_EXISTS,
                f"기존 파일을 보존하기 위해 중단했습니다: {joined}. 덮어쓰려면 --overwrite를 사용하세요.",
            )
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def _temporary_path(self, destination: Path) -> Path:
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        if temporary.exists():
            raise NiaCaseExportError(
                NiaCaseExportErrorCode.TEMPORARY_OUTPUT_EXISTS,
                f"임시 출력 경로가 이미 존재합니다: {temporary}",
            )
        return temporary

    def _write_export(
        self,
        output_temp_path: Path,
        archives: list[NiaCaseInputArchive],
    ) -> NiaCaseExportManifest:
        seen_case_ids: set[str] = set()
        archive_results: list[NiaCaseArchiveManifestEntry] = []
        training_record_count = 0
        validation_record_count = 0

        with output_temp_path.open("x", encoding="utf-8", newline="\n") as output_file:
            for archive in archives:
                entries = list(self._loader.iter_entries([archive.path]))
                for entry in entries:
                    case_id = entry.record.info.id
                    if case_id in seen_case_ids:
                        raise NiaCaseExportError(
                            NiaCaseExportErrorCode.DUPLICATE_CASE_ID,
                            f"중복 case_id가 발견됐습니다: {case_id} ({archive.path})",
                        )
                    seen_case_ids.add(case_id)

                output_record_count = 0
                for entry in self._age_filter.filter(entries):
                    document = self._builder.build(entry.record)
                    if document.text_version != TEXT_VERSION:
                        raise NiaCaseExportError(
                            NiaCaseExportErrorCode.TEXT_VERSION_MISMATCH,
                            f"예상={TEXT_VERSION}, 실제={document.text_version}, case_id={document.case_id}",
                        )
                    export_record = NiaCaseExportRecord(
                        dataset_split=archive.dataset_split,
                        source=NiaCaseSource(
                            archive_name=archive.path.name,
                            member_name=entry.source.member_name,
                            line_number=entry.source.line_number,
                        ),
                        document=document,
                    )
                    output_file.write(export_record.model_dump_json())
                    output_file.write("\n")
                    output_record_count += 1

                archive_results.append(
                    NiaCaseArchiveManifestEntry(
                        archive_name=archive.path.name,
                        dataset_split=archive.dataset_split,
                        input_record_count=len(entries),
                        output_record_count=output_record_count,
                    )
                )
                if archive.dataset_split is NiaCaseDatasetSplit.TRAINING:
                    training_record_count += output_record_count
                else:
                    validation_record_count += output_record_count

        return NiaCaseExportManifest(
            text_version=TEXT_VERSION,
            input_archive_count=len(archives),
            input_record_count=sum(item.input_record_count for item in archive_results),
            output_record_count=training_record_count + validation_record_count,
            training_record_count=training_record_count,
            validation_record_count=validation_record_count,
            duplicate_case_id_count=0,
            failed_record_count=0,
            archives=archive_results,
            # 실제 해시는 파일을 닫은 뒤 계산해서 model_copy로 교체한다.
            output_sha256="0" * 64,
        )

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            while chunk := file.read(SHA256_READ_SIZE_BYTES):
                digest.update(chunk)
        return digest.hexdigest()

    def _write_manifest(self, path: Path, manifest: NiaCaseExportManifest) -> None:
        serialized = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
        path.write_text(f"{serialized}\n", encoding="utf-8", newline="\n")

    def _publish(
        self,
        request: NiaCaseExportRequest,
        output_temp_path: Path,
        manifest_temp_path: Path,
    ) -> None:
        if not request.overwrite:
            self._assert_destination_still_absent(request.output_path)
            self._assert_destination_still_absent(request.manifest_path)
        output_temp_path.replace(request.output_path)
        manifest_temp_path.replace(request.manifest_path)

    def _assert_destination_still_absent(self, path: Path) -> None:
        if path.exists():
            raise NiaCaseExportError(
                NiaCaseExportErrorCode.OUTPUT_ALREADY_EXISTS,
                f"export 도중 대상 파일이 생성되어 덮어쓰지 않았습니다: {path}",
            )


class NiaCaseExportCli:
    def run(self, argv: Sequence[str] | None = None) -> int:
        self._configure_stdout()
        arguments = self._parser().parse_args(argv)
        request = NiaCaseExportRequest(
            input_root=arguments.input_root,
            output_path=arguments.output,
            manifest_path=arguments.manifest,
            overwrite=arguments.overwrite,
        )
        result = NiaCaseExporter().export(request)
        self._print_result(result)
        return 0

    def _configure_stdout(self) -> None:
        # Windows 기본 cp949에서는 한글 진행 메시지가 깨질 수 있어 실행 진입점에서만 UTF-8로 맞춘다.
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="AI Hub Q-CoT-A에서 10~39세 NIA Case Document JSONL을 생성합니다.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        parser.add_argument(
            "--input-root",
            type=Path,
            required=True,
            help="AI Hub '03.스킨케어 성분-효능 추천 데이터' 최상위 폴더",
        )
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
        parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="기존 JSONL과 manifest를 명시적으로 덮어씁니다.",
        )
        return parser

    def _print_result(self, result: NiaCaseExportResult) -> None:
        manifest = result.manifest
        print("NIA Case Document export 완료")
        print(f"- 입력: {manifest.input_record_count:,}건 / ZIP {manifest.input_archive_count}개")
        print(
            f"- 출력: {manifest.output_record_count:,}건 "
            f"(training {manifest.training_record_count:,}, "
            f"validation {manifest.validation_record_count:,})"
        )
        print(f"- JSONL: {result.output_path}")
        print(f"- manifest: {result.manifest_path}")
        print(f"- SHA-256: {manifest.output_sha256}")


if __name__ == "__main__":
    raise SystemExit(NiaCaseExportCli().run())
