"""NIA Claim export JSONL을 DB에 적재할 때 사용하는 Backend 소유 타입."""

from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.claim_chunk import (
    ClaimIngestionDecision,
    ClaimIngredientMatchingStatus,
    ClaimIngredientRefRole,
    ClaimPriority,
    ClaimStatementType,
    ClaimSupportStatus,
)
from models.claim_document import ClaimDatasetSplit


class ClaimIngestionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ClaimSourceSpanInput(ClaimIngestionModel):
    json_path: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end <= self.start:
            raise ValueError("source span의 end는 start보다 커야 합니다.")
        if self.end - self.start != len(self.quote):
            raise ValueError("source span 범위와 quote 길이가 다릅니다.")
        return self


class ClaimIngredientRefInput(ClaimIngestionModel):
    ingredient_id: UUID | None = None
    raw_name: str | None = Field(default=None, min_length=1)
    matching_status: ClaimIngredientMatchingStatus
    role: ClaimIngredientRefRole

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.ingredient_id is None and self.raw_name is None:
            raise ValueError("ingredient_id와 raw_name 중 하나는 있어야 합니다.")
        if (
            self.ingredient_id is not None
            and self.matching_status is not ClaimIngredientMatchingStatus.MATCHED
        ):
            raise ValueError("ingredient_id가 있으면 matching_status는 matched여야 합니다.")
        return self


class ClaimStatementInput(ClaimIngestionModel):
    statement_id: str = Field(min_length=1)
    statement_type: ClaimStatementType
    content: str = Field(min_length=1)
    source_spans: list[ClaimSourceSpanInput] = Field(min_length=1)
    decision: ClaimIngestionDecision
    priority: ClaimPriority
    support_status: ClaimSupportStatus
    ingredient_refs: list[ClaimIngredientRefInput]


class ClaimExportRecordInput(ClaimIngestionModel):
    source_record_id: str = Field(min_length=1)
    annotation_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    dataset_split: ClaimDatasetSplit
    skin_concerns_raw: list[str]
    production_ready: bool
    statements: list[ClaimStatementInput]

    @model_validator(mode="after")
    def validate_statement_ids(self) -> Self:
        statement_ids = [statement.statement_id for statement in self.statements]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError(f"statement_id 중복: {self.source_record_id}")
        return self


class ClaimExportManifestInput(ClaimIngestionModel):
    export_version: str = Field(min_length=1)
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


class ClaimIngestionRequest(ClaimIngestionModel):
    input_path: Path
    manifest_path: Path
    batch_size: int = Field(default=16, ge=1)


class ClaimIngestionPayload(ClaimIngestionModel):
    records: list[ClaimExportRecordInput]
    manifest: ClaimExportManifestInput


class ClaimIngestionResult(ClaimIngestionModel):
    document_count: int = Field(ge=0)
    statement_count: int = Field(ge=0)
    embedded_count: int = Field(ge=0)
    skipped_statement_count: int = Field(ge=0)
    annotation_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)


class ClaimEmbeddingTarget(ClaimIngestionModel):
    source_record_id: str = Field(min_length=1)
    statement: ClaimStatementInput
