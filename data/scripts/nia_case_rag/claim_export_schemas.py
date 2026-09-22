"""오프라인 NIA annotation을 Backend Claim 적재로 넘기는 파일 계약 타입."""

from enum import StrEnum
from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data.scripts.nia_claim_ingestion_policy import (
    NiaClaimIngestionDecision,
    NiaClaimPriority,
)
from data.scripts.nia_labeling_schemas import (
    NiaDatasetSplit,
    NiaIngredientMatchingStatus,
    NiaSourceSpan,
    NiaStatementType,
    NiaSupportStatus,
)

NIA_CLAIM_EXPORT_VERSION = "nia_claim_export/v1"


class ClaimExportIngredientRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    UNSPECIFIED = "unspecified"


class ClaimExportModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ClaimExportIngredientRef(ClaimExportModel):
    ingredient_id: UUID | None = None
    raw_name: str | None = Field(default=None, min_length=1)
    matching_status: NiaIngredientMatchingStatus
    role: ClaimExportIngredientRole = ClaimExportIngredientRole.UNSPECIFIED

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.ingredient_id is None and self.raw_name is None:
            raise ValueError("ingredient_id와 raw_name 중 하나는 있어야 합니다.")
        if (
            self.ingredient_id is not None
            and self.matching_status is not NiaIngredientMatchingStatus.MATCHED
        ):
            raise ValueError("ingredient_id가 있으면 matching_status는 matched여야 합니다.")
        return self


class ClaimExportStatement(ClaimExportModel):
    statement_id: str = Field(min_length=1)
    statement_type: NiaStatementType
    content: str = Field(min_length=1)
    source_spans: list[NiaSourceSpan] = Field(min_length=1)
    decision: NiaClaimIngestionDecision
    priority: NiaClaimPriority
    support_status: NiaSupportStatus
    ingredient_refs: list[ClaimExportIngredientRef]


class ClaimExportRecord(ClaimExportModel):
    source_record_id: str = Field(min_length=1)
    annotation_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    dataset_split: NiaDatasetSplit
    skin_concerns_raw: list[str]
    production_ready: bool
    statements: list[ClaimExportStatement]

    @model_validator(mode="after")
    def validate_statement_ids(self) -> Self:
        statement_ids = [statement.statement_id for statement in self.statements]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError(f"statement_id가 중복되었습니다: {self.source_record_id}")
        return self


class ClaimExportManifest(ClaimExportModel):
    export_version: str = Field(default=NIA_CLAIM_EXPORT_VERSION, min_length=1)
    annotation_version: str = Field(min_length=1)
    document_count: int = Field(ge=0)
    statement_count: int = Field(ge=0)
    ingestible_statement_count: int = Field(ge=0)
    blocked_statement_count: int = Field(ge=0)
    human_review_statement_count: int = Field(ge=0)
    training_document_count: int = Field(ge=0)
    validation_document_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.document_count != self.training_document_count + self.validation_document_count:
            raise ValueError("전체 document 수와 split별 document 수 합계가 다릅니다.")
        categorized = (
            self.ingestible_statement_count
            + self.blocked_statement_count
            + self.human_review_statement_count
        )
        if self.statement_count != categorized:
            raise ValueError("전체 statement 수와 decision별 statement 수 합계가 다릅니다.")
        return self


class ClaimExportRequest(ClaimExportModel):
    annotations_path: Path
    decisions_path: Path
    output_path: Path
    manifest_path: Path
    overwrite: bool = False

    @model_validator(mode="after")
    def validate_output_paths(self) -> Self:
        if self.output_path.resolve() == self.manifest_path.resolve():
            raise ValueError("Claim JSONL과 manifest 경로는 서로 달라야 합니다.")
        return self


class ClaimExportResult(ClaimExportModel):
    output_path: Path
    manifest_path: Path
    manifest: ClaimExportManifest


class ClaimIngestionDecisionRecord(ClaimExportModel):
    record_id: str = Field(min_length=1)
    statement_id: str = Field(min_length=1)
    statement_type: NiaStatementType
    decision: NiaClaimIngestionDecision
    priority: NiaClaimPriority
