"""NIA Case Document JSONL export 경계 타입.

원본 로더/연령 필터/Case Document Builder의 결과를 파일로 넘길 때 필요한 provenance와
검증 통계를 정의한다. DB·임베딩 형식은 이 모듈의 책임이 아니다.
"""

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data.scripts.nia_case_document_schemas import NiaCaseDocument


class NiaCaseDatasetSplit(StrEnum):
    TRAINING = "training"
    VALIDATION = "validation"


class NiaCaseSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    archive_name: str = Field(min_length=1)
    member_name: str | None = Field(default=None, min_length=1)
    line_number: int = Field(ge=1)


class NiaCaseInputArchive(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    dataset_split: NiaCaseDatasetSplit


class NiaCaseExportRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_split: NiaCaseDatasetSplit
    source: NiaCaseSource
    document: NiaCaseDocument


class NiaCaseArchiveManifestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    archive_name: str = Field(min_length=1)
    dataset_split: NiaCaseDatasetSplit
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)


class NiaCaseExportManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    text_version: str = Field(min_length=1)
    input_archive_count: int = Field(ge=1)
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)
    training_record_count: int = Field(ge=0)
    validation_record_count: int = Field(ge=0)
    duplicate_case_id_count: int = Field(default=0, ge=0, le=0)
    failed_record_count: int = Field(default=0, ge=0, le=0)
    archives: list[NiaCaseArchiveManifestEntry] = Field(min_length=1)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.input_archive_count != len(self.archives):
            raise ValueError("manifest의 입력 archive 수와 archive 목록 길이가 다릅니다.")
        if self.input_record_count != sum(item.input_record_count for item in self.archives):
            raise ValueError("manifest의 전체 입력 건수와 archive별 입력 건수 합계가 다릅니다.")
        if self.output_record_count != sum(item.output_record_count for item in self.archives):
            raise ValueError("manifest의 전체 출력 건수와 archive별 출력 건수 합계가 다릅니다.")
        if self.output_record_count != self.training_record_count + self.validation_record_count:
            raise ValueError("manifest의 전체 출력 건수와 split별 출력 건수 합계가 다릅니다.")
        return self


class NiaCaseExportRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_root: Path
    output_path: Path
    manifest_path: Path
    overwrite: bool = False

    @model_validator(mode="after")
    def validate_output_paths(self) -> Self:
        if self.output_path.resolve() == self.manifest_path.resolve():
            raise ValueError("NIA Case JSONL과 manifest 경로는 서로 달라야 합니다.")
        return self


class NiaCaseExportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    output_path: Path
    manifest_path: Path
    manifest: NiaCaseExportManifest
