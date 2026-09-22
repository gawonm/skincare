"""production annotation과 ingestion decision을 Backend Claim 적재 JSONL로 변환한다."""

import argparse
import hashlib
import io
import json
import sys
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from data.scripts.nia_case_rag.claim_export_schemas import (
    ClaimExportIngredientRef,
    ClaimExportManifest,
    ClaimExportRecord,
    ClaimExportRequest,
    ClaimExportResult,
    ClaimExportStatement,
    ClaimIngestionDecisionRecord,
)
from data.scripts.nia_claim_ingestion_policy import NiaClaimIngestionDecision
from data.scripts.nia_labeling_schemas import (
    NiaCaseObservationStatement,
    NiaCauseClaimStatement,
    NiaCombinationClaimStatement,
    NiaContextualFactorStatement,
    NiaDatasetSplit,
    NiaIngredientEffectClaimStatement,
    NiaIngredientMatchingStatus,
    NiaIngredientSubject,
    NiaLabelingDocument,
    NiaPrecautionRelation,
    NiaPrecautionStatement,
    NiaStatement,
    NiaUsageInstructionStatement,
)

DEFAULT_ANNOTATIONS_PATH = Path("data/processed/nia_10s_30s_annotations_production.jsonl")
DEFAULT_DECISIONS_PATH = Path("data/processed/nia_10s_30s_claim_ingestion_production.jsonl")
DEFAULT_OUTPUT_PATH = Path("data/processed/nia_claim_documents_production.jsonl")
DEFAULT_MANIFEST_PATH = Path("data/processed/nia_claim_documents_production.manifest.json")
SHA256_READ_SIZE_BYTES = 1024 * 1024


class ClaimExportErrorCode(StrEnum):
    INPUT_NOT_FOUND = "input_not_found"
    INVALID_INPUT = "invalid_input"
    DUPLICATE_DOCUMENT = "duplicate_document"
    DUPLICATE_DECISION = "duplicate_decision"
    DECISION_MISMATCH = "decision_mismatch"
    MIXED_ANNOTATION_VERSION = "mixed_annotation_version"
    OUTPUT_ALREADY_EXISTS = "output_already_exists"


class ClaimExportError(RuntimeError):
    def __init__(self, code: ClaimExportErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"NIA Claim export 실패 [{code.value}]: {message}")


class ClaimStatementContentMapper:
    """statement 타입별 필드를 검색 가능한 문장으로 손실 없이 조립한다."""

    def map(self, statement: NiaStatement, skin_concerns: tuple[str, ...]) -> str:
        if isinstance(statement, NiaCaseObservationStatement):
            return " ".join([*skin_concerns, statement.subject]).strip()
        if isinstance(statement, NiaIngredientEffectClaimStatement):
            name = statement.subject.raw_name_ko or statement.subject.raw_name
            concentration = (
                f" 농도: {statement.concentration_raw}" if statement.concentration_raw else ""
            )
            return f"성분: {name} 효과: {statement.object}{concentration}"
        if isinstance(statement, NiaPrecautionStatement):
            prefix = "주의" if statement.relation is NiaPrecautionRelation.AVOID else "자극 가능성"
            return f"{prefix}: {statement.subject}"
        if isinstance(statement, NiaUsageInstructionStatement):
            return statement.action
        if isinstance(statement, NiaCauseClaimStatement):
            objects = ", ".join(statement.objects)
            relation = (
                "주된 원인으로 언급됨"
                if statement.relation.value == "described_as_main_cause_of"
                else "기여 원인으로 언급됨"
            )
            scope = f" 범위: {statement.scope_text}" if statement.scope_text else ""
            return f"{statement.subject}: {objects}의 {relation}{scope}"
        if isinstance(statement, NiaCombinationClaimStatement):
            names = " + ".join(
                subject.raw_name_ko or subject.raw_name for subject in statement.subjects
            )
            return f"성분 조합: {names} 효과: {statement.object}"
        if isinstance(statement, NiaContextualFactorStatement):
            return f"배경 요인: {statement.factor_raw} {statement.details_raw}".strip()
        raise TypeError(f"지원하지 않는 NIA statement 타입입니다: {type(statement).__name__}")


class ClaimIngredientRefMapper:
    def map(self, statement: NiaStatement) -> list[ClaimExportIngredientRef]:
        if isinstance(statement, NiaIngredientEffectClaimStatement):
            return [self._from_subject(statement.subject)]
        if isinstance(statement, NiaCombinationClaimStatement):
            return [self._from_subject(subject) for subject in statement.subjects]
        if isinstance(statement, NiaUsageInstructionStatement):
            return [
                ClaimExportIngredientRef(
                    ingredient_id=ingredient_id,
                    raw_name=None,
                    matching_status=NiaIngredientMatchingStatus.MATCHED,
                )
                for ingredient_id in statement.ingredient_ids
            ]
        return []

    def _from_subject(self, subject: NiaIngredientSubject) -> ClaimExportIngredientRef:
        return ClaimExportIngredientRef(
            ingredient_id=subject.ingredient_id,
            raw_name=subject.raw_name,
            matching_status=subject.matching_status,
        )


class ClaimExporter:
    def __init__(
        self,
        content_mapper: ClaimStatementContentMapper | None = None,
        ingredient_mapper: ClaimIngredientRefMapper | None = None,
    ) -> None:
        self._content_mapper = content_mapper or ClaimStatementContentMapper()
        self._ingredient_mapper = ingredient_mapper or ClaimIngredientRefMapper()

    def export(self, request: ClaimExportRequest) -> ClaimExportResult:
        self._validate_inputs(request)
        self._prepare_destinations(request)
        documents = self._read_documents(request.annotations_path)
        decisions = self._read_decisions(request.decisions_path)
        records = self._map_records(documents, decisions)
        output_temp = self._temporary_path(request.output_path)
        manifest_temp = self._temporary_path(request.manifest_path)
        try:
            self._write_records(output_temp, records)
            manifest = self._build_manifest(records, self._sha256(output_temp))
            self._write_manifest(manifest_temp, manifest)
            self._publish(request, output_temp, manifest_temp)
        except (OSError, RuntimeError, ValueError):
            output_temp.unlink(missing_ok=True)
            manifest_temp.unlink(missing_ok=True)
            raise
        return ClaimExportResult(
            output_path=request.output_path,
            manifest_path=request.manifest_path,
            manifest=manifest,
        )

    def _validate_inputs(self, request: ClaimExportRequest) -> None:
        missing = [
            str(path)
            for path in (request.annotations_path, request.decisions_path)
            if not path.is_file()
        ]
        if missing:
            raise ClaimExportError(
                ClaimExportErrorCode.INPUT_NOT_FOUND,
                f"필수 입력 파일이 없습니다: {missing}",
            )

    def _prepare_destinations(self, request: ClaimExportRequest) -> None:
        existing = [path for path in (request.output_path, request.manifest_path) if path.exists()]
        if existing and not request.overwrite:
            raise ClaimExportError(
                ClaimExportErrorCode.OUTPUT_ALREADY_EXISTS,
                f"기존 산출물을 보존하기 위해 중단했습니다: {existing}",
            )
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_documents(self, path: Path) -> list[NiaLabelingDocument]:
        documents: list[NiaLabelingDocument] = []
        seen_keys: set[tuple[str, str]] = set()
        with path.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                try:
                    document = NiaLabelingDocument.model_validate_json(line)
                except ValidationError as exc:
                    raise ClaimExportError(
                        ClaimExportErrorCode.INVALID_INPUT,
                        f"annotation 스키마 오류: {path}:{line_number}: {exc}",
                    ) from exc
                key = (document.source.record_id, document.annotation_version)
                if key in seen_keys:
                    raise ClaimExportError(
                        ClaimExportErrorCode.DUPLICATE_DOCUMENT,
                        f"annotation document 중복: {key}",
                    )
                seen_keys.add(key)
                documents.append(document)
        versions = {document.annotation_version for document in documents}
        if len(versions) > 1:
            raise ClaimExportError(
                ClaimExportErrorCode.MIXED_ANNOTATION_VERSION,
                f"annotation_version이 섞여 있습니다: {sorted(versions)}",
            )
        return documents

    def _read_decisions(self, path: Path) -> dict[tuple[str, str], ClaimIngestionDecisionRecord]:
        decisions: dict[tuple[str, str], ClaimIngestionDecisionRecord] = {}
        with path.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                try:
                    decision = ClaimIngestionDecisionRecord.model_validate_json(line)
                except ValidationError as exc:
                    raise ClaimExportError(
                        ClaimExportErrorCode.INVALID_INPUT,
                        f"ingestion decision 스키마 오류: {path}:{line_number}: {exc}",
                    ) from exc
                key = (decision.record_id, decision.statement_id)
                if key in decisions:
                    raise ClaimExportError(
                        ClaimExportErrorCode.DUPLICATE_DECISION,
                        f"ingestion decision 중복: {key}",
                    )
                decisions[key] = decision
        return decisions

    def _map_records(
        self,
        documents: list[NiaLabelingDocument],
        decisions: dict[tuple[str, str], ClaimIngestionDecisionRecord],
    ) -> list[ClaimExportRecord]:
        records: list[ClaimExportRecord] = []
        used_decisions: set[tuple[str, str]] = set()
        for document in documents:
            statements: list[ClaimExportStatement] = []
            for statement in document.statements:
                key = (document.source.record_id, statement.statement_id)
                decision = decisions.get(key)
                if decision is None:
                    raise ClaimExportError(
                        ClaimExportErrorCode.DECISION_MISMATCH,
                        f"statement의 ingestion decision이 없습니다: {key}",
                    )
                if decision.statement_type is not statement.statement_type:
                    raise ClaimExportError(
                        ClaimExportErrorCode.DECISION_MISMATCH,
                        f"statement_type이 다릅니다: {key}",
                    )
                used_decisions.add(key)
                statements.append(
                    ClaimExportStatement(
                        statement_id=statement.statement_id,
                        statement_type=statement.statement_type,
                        content=self._content_mapper.map(
                            statement, document.case_context.skin_concerns_raw
                        ),
                        source_spans=list(statement.source_spans),
                        decision=decision.decision,
                        priority=decision.priority,
                        support_status=statement.support_status,
                        ingredient_refs=self._ingredient_mapper.map(statement),
                    )
                )
            records.append(
                ClaimExportRecord(
                    source_record_id=document.source.record_id,
                    annotation_version=document.annotation_version,
                    schema_version=document.schema_version,
                    dataset_split=document.source.dataset_split,
                    skin_concerns_raw=list(document.case_context.skin_concerns_raw),
                    production_ready=document.production_ready,
                    statements=statements,
                )
            )
        unused_decisions = set(decisions) - used_decisions
        if unused_decisions:
            raise ClaimExportError(
                ClaimExportErrorCode.DECISION_MISMATCH,
                f"annotation에 없는 ingestion decision이 있습니다: {sorted(unused_decisions)[:5]}",
            )
        return records

    def _write_records(self, path: Path, records: list[ClaimExportRecord]) -> None:
        with path.open("x", encoding="utf-8", newline="\n") as output_file:
            for record in records:
                output_file.write(record.model_dump_json())
                output_file.write("\n")

    def _build_manifest(
        self, records: list[ClaimExportRecord], output_sha256: str
    ) -> ClaimExportManifest:
        versions = {record.annotation_version for record in records}
        if len(versions) != 1:
            raise ClaimExportError(
                ClaimExportErrorCode.MIXED_ANNOTATION_VERSION,
                f"단일 annotation_version이 필요합니다: {sorted(versions)}",
            )
        decisions = Counter(
            statement.decision for record in records for statement in record.statements
        )
        ingestible_count = sum(
            decisions[decision]
            for decision in (
                NiaClaimIngestionDecision.INGESTIBLE_STRUCTURED,
                NiaClaimIngestionDecision.INGESTIBLE_FREE_TEXT,
            )
        )
        split_counts = Counter(record.dataset_split for record in records)
        return ClaimExportManifest(
            annotation_version=next(iter(versions)),
            document_count=len(records),
            statement_count=sum(len(record.statements) for record in records),
            ingestible_statement_count=ingestible_count,
            blocked_statement_count=decisions[NiaClaimIngestionDecision.BLOCKED],
            human_review_statement_count=decisions[NiaClaimIngestionDecision.HUMAN_REVIEW],
            training_document_count=split_counts[NiaDatasetSplit.TRAINING],
            validation_document_count=split_counts[NiaDatasetSplit.VALIDATION],
            output_sha256=output_sha256,
        )

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as input_file:
            while chunk := input_file.read(SHA256_READ_SIZE_BYTES):
                digest.update(chunk)
        return digest.hexdigest()

    def _write_manifest(self, path: Path, manifest: ClaimExportManifest) -> None:
        serialized = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
        path.write_text(f"{serialized}\n", encoding="utf-8", newline="\n")

    def _temporary_path(self, destination: Path) -> Path:
        return destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")

    def _publish(self, request: ClaimExportRequest, output_temp: Path, manifest_temp: Path) -> None:
        if not request.overwrite:
            for destination in (request.output_path, request.manifest_path):
                if destination.exists():
                    raise ClaimExportError(
                        ClaimExportErrorCode.OUTPUT_ALREADY_EXISTS,
                        f"export 도중 대상 파일이 생성됐습니다: {destination}",
                    )
        output_temp.replace(request.output_path)
        manifest_temp.replace(request.manifest_path)


class ClaimExportCli:
    def run(self, argv: Sequence[str] | None = None) -> int:
        self._configure_stdout()
        arguments = self._parser().parse_args(argv)
        result = ClaimExporter().export(
            ClaimExportRequest(
                annotations_path=arguments.annotations,
                decisions_path=arguments.decisions,
                output_path=arguments.output,
                manifest_path=arguments.manifest,
                overwrite=arguments.overwrite,
            )
        )
        self._print_result(result)
        return 0

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="NIA production annotation을 Backend Claim 적재 JSONL로 변환합니다.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS_PATH)
        parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS_PATH)
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
        parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
        parser.add_argument("--overwrite", action="store_true")
        return parser

    def _configure_stdout(self) -> None:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def _print_result(self, result: ClaimExportResult) -> None:
        manifest = result.manifest
        print("NIA Claim export 완료")
        print(f"- document: {manifest.document_count:,}건")
        print(f"- statement: {manifest.statement_count:,}건")
        print(f"- 적재 가능 statement: {manifest.ingestible_statement_count:,}건")
        print(f"- JSONL: {result.output_path}")
        print(f"- manifest: {result.manifest_path}")


if __name__ == "__main__":
    raise SystemExit(ClaimExportCli().run())
