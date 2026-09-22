"""NIA 원본 record_id를 annotation provenance와 연결한다.

과거 구조 감사 JSONL과 새 production corpus provenance JSONL을 같은 검증 경계로 읽는다.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from data.scripts.nia_labeling_schemas import NiaDatasetSplit

_AUDIT_PATH = Path("data/manual_review/nia/nia_structural_audit_9000.jsonl")


class NiaRecordRiskLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNASSESSED = "UNASSESSED"


class NiaRecordProvenance(BaseModel):
    # 새 provenance의 원본 위치 필드는 production processor가 아직 사용하지 않으므로 보존하되
    # 이 호환 모델에서는 무시한다. 권위 있는 전체 형식은 annotation_corpus_schemas가 소유한다.
    model_config = ConfigDict(frozen=True, extra="ignore")

    record_id: str = Field(min_length=1)
    dataset_split: NiaDatasetSplit
    source_archive: str = Field(min_length=1)
    info_target_concern: str = Field(min_length=1)
    archive_mismatch: bool
    risk_level: NiaRecordRiskLevel = NiaRecordRiskLevel.UNASSESSED
    review_reasons: tuple[str, ...] = ()


class NiaRecordProvenanceError(RuntimeError):
    pass


class NiaRecordProvenanceIndex:
    def __init__(self, audit_path: Path = _AUDIT_PATH) -> None:
        self._by_record_id: dict[str, NiaRecordProvenance] = {}
        try:
            with audit_path.open("r", encoding="utf-8") as input_file:
                for line_number, line in enumerate(input_file, start=1):
                    try:
                        provenance = NiaRecordProvenance.model_validate_json(line)
                    except ValidationError as exc:
                        raise NiaRecordProvenanceError(
                            f"provenance 스키마 오류: {audit_path}:{line_number}: {exc}"
                        ) from exc
                    if provenance.record_id in self._by_record_id:
                        raise NiaRecordProvenanceError(
                            f"provenance record_id 중복: {audit_path}:{line_number}: "
                            f"{provenance.record_id}"
                        )
                    self._by_record_id[provenance.record_id] = provenance
        except OSError as exc:
            raise NiaRecordProvenanceError(
                f"provenance 파일을 읽지 못했습니다: {audit_path}: {exc}"
            ) from exc

    def get(self, record_id: str) -> NiaRecordProvenance | None:
        return self._by_record_id.get(record_id)
