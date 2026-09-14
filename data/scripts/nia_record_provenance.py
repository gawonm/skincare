"""`nia_qa_10s_30s.jsonl`에는 없는 `source_archive`/`dataset_split`을,
`data/manual_review/nia/nia_structural_audit_9000.jsonl`(9,000건 전체 구조 감사 결과)에서
`record_id`로 join해 보강한다. 원본 zip을 다시 파싱하지 않는다.
"""

import json
from pathlib import Path
from typing import NamedTuple

_AUDIT_PATH = Path("data/manual_review/nia/nia_structural_audit_9000.jsonl")


class NiaRecordProvenance(NamedTuple):
    dataset_split: str
    source_archive: str
    info_target_concern: str
    archive_mismatch: bool
    risk_level: str
    review_reasons: tuple[str, ...]


class NiaRecordProvenanceIndex:
    def __init__(self, audit_path: Path = _AUDIT_PATH) -> None:
        self._by_record_id: dict[str, NiaRecordProvenance] = {}
        with audit_path.open("r", encoding="utf-8") as file:
            for line in file:
                row = json.loads(line)
                self._by_record_id[row["record_id"]] = NiaRecordProvenance(
                    dataset_split=row["dataset_split"],
                    source_archive=row["source_archive"],
                    info_target_concern=row["info_target_concern"],
                    archive_mismatch=row["archive_mismatch"],
                    risk_level=row["risk_level"],
                    review_reasons=tuple(row["review_reasons"]),
                )

    def get(self, record_id: str) -> NiaRecordProvenance | None:
        return self._by_record_id.get(record_id)
