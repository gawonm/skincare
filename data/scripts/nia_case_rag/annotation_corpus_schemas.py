"""NIA production annotation 입력 corpus export 타입."""

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data.scripts.nia_case_rag.export_schemas import NiaCaseDatasetSplit

NIA_ANNOTATION_CORPUS_VERSION = "nia_annotation_corpus/v1"


class NiaAnnotationCorpusRiskLevel(StrEnum):
    """구조 감사를 수행하지 않은 새 export임을 과거 감사 결과와 구분한다."""

    UNASSESSED = "UNASSESSED"


class NiaAnnotationCorpusModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NiaAnnotationCorpusProvenance(NiaAnnotationCorpusModel):
    record_id: str = Field(min_length=1)
    dataset_split: NiaCaseDatasetSplit
    source_archive: str = Field(min_length=1)
    source_member: str | None = Field(default=None, min_length=1)
    source_line_number: int = Field(ge=1)
    info_target_concern: str = Field(min_length=1)
    archive_mismatch: bool
    risk_level: NiaAnnotationCorpusRiskLevel = NiaAnnotationCorpusRiskLevel.UNASSESSED
    review_reasons: tuple[str, ...] = ()


class NiaAnnotationCorpusArchiveEntry(NiaAnnotationCorpusModel):
    archive_name: str = Field(min_length=1)
    dataset_split: NiaCaseDatasetSplit
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)


class NiaAnnotationCorpusManifest(NiaAnnotationCorpusModel):
    corpus_version: str = Field(default=NIA_ANNOTATION_CORPUS_VERSION, min_length=1)
    input_archive_count: int = Field(ge=1)
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)
    training_record_count: int = Field(ge=0)
    validation_record_count: int = Field(ge=0)
    duplicate_record_id_count: int = Field(default=0, ge=0, le=0)
    missing_case_id_count: int = Field(default=0, ge=0, le=0)
    extra_case_id_count: int = Field(default=0, ge=0, le=0)
    archives: list[NiaAnnotationCorpusArchiveEntry] = Field(min_length=1)
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_documents_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.input_archive_count != len(self.archives):
            raise ValueError("manifest 입력 archive 수와 archive 목록 길이가 다릅니다.")
        if self.input_record_count != sum(item.input_record_count for item in self.archives):
            raise ValueError("manifest 전체 입력 건수와 archive별 입력 건수 합계가 다릅니다.")
        if self.output_record_count != sum(item.output_record_count for item in self.archives):
            raise ValueError("manifest 전체 출력 건수와 archive별 출력 건수 합계가 다릅니다.")
        if self.output_record_count != self.training_record_count + self.validation_record_count:
            raise ValueError("manifest 전체 출력 건수와 split별 출력 건수 합계가 다릅니다.")
        return self


class NiaAnnotationCorpusExportRequest(NiaAnnotationCorpusModel):
    input_root: Path
    case_documents_path: Path
    output_path: Path
    provenance_path: Path
    manifest_path: Path
    overwrite: bool = False

    @model_validator(mode="after")
    def validate_output_paths(self) -> Self:
        paths = [
            self.output_path.resolve(),
            self.provenance_path.resolve(),
            self.manifest_path.resolve(),
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("corpus, provenance, manifest 출력 경로는 서로 달라야 합니다.")
        return self


class NiaAnnotationCorpusExportResult(NiaAnnotationCorpusModel):
    output_path: Path
    provenance_path: Path
    manifest_path: Path
    manifest: NiaAnnotationCorpusManifest
