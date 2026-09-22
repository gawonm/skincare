"""NIA Case JSONL을 DB에 적재할 때 사용하는 Backend 소유 타입."""

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

NIA_CASE_TEXT_VERSION_V1 = "nia_case_text/v1"


class NiaCaseIngestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NiaCaseDatasetSplit(StrEnum):
    TRAINING = "training"
    VALIDATION = "validation"


class NiaCaseIngestionMode(StrEnum):
    UPSERT = "upsert"


class NiaCaseSourceInput(NiaCaseIngestionModel):
    archive_name: str = Field(min_length=1)
    member_name: str | None = Field(default=None, min_length=1)
    line_number: int = Field(ge=1)


class NiaCaseExternalFactorInput(BaseModel):
    # Data 원본 schema가 미래 필드를 보존하므로 external 항목도 알 수 없는 필드를 버리지 않는다.
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)

    priority: int
    factor: str
    details: str


class NiaCaseMetadataInput(NiaCaseIngestionModel):
    case_id: str = Field(min_length=1)
    source_survey_id: str = Field(min_length=1)
    image_filename: str
    evidence_sources: list[str]
    target_concern: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    skin_concerns: list[str]
    initial_skin_condition: str
    external: list[NiaCaseExternalFactorInput]


class NiaCaseDocumentInput(NiaCaseIngestionModel):
    case_id: str = Field(min_length=1)
    page_content: str = Field(min_length=1)
    embedding_text: str = Field(min_length=1)
    text_version: str = Field(min_length=1)
    metadata: NiaCaseMetadataInput

    @model_validator(mode="after")
    def validate_case_identity(self) -> Self:
        if self.case_id != self.metadata.case_id:
            raise ValueError("document.case_id와 document.metadata.case_id가 다릅니다.")
        if (
            self.text_version == NIA_CASE_TEXT_VERSION_V1
            and self.page_content != self.embedding_text
        ):
            raise ValueError(
                "nia_case_text/v1에서는 document.page_content와 embedding_text가 같아야 합니다."
            )
        return self


class NiaCaseExportRecordInput(NiaCaseIngestionModel):
    dataset_split: NiaCaseDatasetSplit
    source: NiaCaseSourceInput
    document: NiaCaseDocumentInput


class NiaCaseArchiveManifestEntryInput(NiaCaseIngestionModel):
    archive_name: str = Field(min_length=1)
    dataset_split: NiaCaseDatasetSplit
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)


class NiaCaseExportManifestInput(NiaCaseIngestionModel):
    text_version: str = Field(min_length=1)
    input_archive_count: int = Field(ge=1)
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)
    training_record_count: int = Field(ge=0)
    validation_record_count: int = Field(ge=0)
    duplicate_case_id_count: int = Field(default=0, ge=0, le=0)
    failed_record_count: int = Field(default=0, ge=0, le=0)
    archives: list[NiaCaseArchiveManifestEntryInput] = Field(min_length=1)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        archive_keys = [(item.archive_name, item.dataset_split) for item in self.archives]
        if len(archive_keys) != len(set(archive_keys)):
            raise ValueError("manifest archive_name/dataset_split 조합이 중복되었습니다.")
        if self.input_archive_count != len(self.archives):
            raise ValueError("manifest 입력 archive 수와 archive 목록 길이가 다릅니다.")
        if self.input_record_count != sum(item.input_record_count for item in self.archives):
            raise ValueError("manifest 전체 입력 건수와 archive별 입력 건수 합계가 다릅니다.")
        if self.output_record_count != sum(item.output_record_count for item in self.archives):
            raise ValueError("manifest 전체 출력 건수와 archive별 출력 건수 합계가 다릅니다.")
        if self.output_record_count != self.training_record_count + self.validation_record_count:
            raise ValueError("manifest 전체 출력 건수와 split별 출력 건수 합계가 다릅니다.")
        return self


class NiaCaseIngestionRequest(NiaCaseIngestionModel):
    input_path: Path
    manifest_path: Path
    mode: NiaCaseIngestionMode = NiaCaseIngestionMode.UPSERT
    batch_size: int = Field(default=16, ge=1)


class NiaCaseIngestionPayload(NiaCaseIngestionModel):
    records: list[NiaCaseExportRecordInput]
    manifest: NiaCaseExportManifestInput


class NiaCaseIngestionResult(NiaCaseIngestionModel):
    total_count: int = Field(ge=0)
    inserted_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    embedded_count: int = Field(ge=0)
    text_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
