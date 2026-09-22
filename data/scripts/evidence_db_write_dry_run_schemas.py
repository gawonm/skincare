"""`FINAL_EVIDENCE_DB_ACTION_PLAN`을 실제 canonical DB(읽기 전용)와 대조하는
dry-run 단계가 주고받는 Pydantic 모델. 이 모델들은 DB에 아무것도 쓰지 않는다."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DocumentAction(StrEnum):
    INSERT = "INSERT"
    REUSE = "REUSE"
    KEEP_IDENTITY = "KEEP_IDENTITY"
    REMOVE = "REMOVE"
    DEFER = "DEFER"


class ChunkAction(StrEnum):
    INSERT = "INSERT"
    REUSE = "REUSE"
    REPLACE = "REPLACE"
    REMOVE = "REMOVE"
    DEFER = "DEFER"


class LinkAction(StrEnum):
    INSERT = "INSERT"
    EXISTS = "EXISTS"
    REUSE = "REUSE"
    REMOVE = "REMOVE"


class MismatchSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class MismatchCategory(StrEnum):
    DOCUMENT = "DOCUMENT"
    CHUNK = "CHUNK"
    LINK = "LINK"
    EMBEDDING = "EMBEDDING"


class Mismatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: MismatchCategory
    key: str
    action: str
    reason: str
    severity: MismatchSeverity


class RowDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    before: int
    delta: int
    after: int


class DryRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: dict[str, int]
    chunks: dict[str, int]
    links: dict[str, int]
    embedding_insert_update_targets: int
    embedding_missing: int
    embedding_duplicate: int
    row_deltas: list[RowDelta]
    mismatches: list[Mismatch]

    @property
    def ready_for_db_write(self) -> bool:
        return not any(m.severity is MismatchSeverity.ERROR for m in self.mismatches)
