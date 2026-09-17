"""Evidence 저장 구조(evidence_document/evidence_chunk/evidence_chunk_ingredient) 검증.

migration을 아직 실행하지 않은 단계라 DB에 직접 넣어보는 테스트는 못 한다 - 대신 SQLAlchemy
metadata(컬럼/제약/FK 선언)와 alembic 리비전 체인을 Python 레벨에서 검증한다. 실제 DB 제약
동작(예: UNIQUE 위반 시 실제로 거부되는지)은 migration 실행 승인 후 tests/db/에서 검증한다.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from core.database import Base
from models.evidence_chunk import EvidenceChunk, evidence_chunk_ingredient
from models.evidence_document import EvidenceDocument

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_evidence_tables_registered_in_metadata() -> None:
    assert "evidence_document" in Base.metadata.tables
    assert "evidence_chunk" in Base.metadata.tables
    assert "evidence_chunk_ingredient" in Base.metadata.tables


def test_evidence_document_has_composite_unique_source_type_source_id() -> None:
    table = EvidenceDocument.__table__
    unique_column_sets = {
        frozenset(col.name for col in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert frozenset({"source_type", "source_id"}) in unique_column_sets
    # 단일 source_id 단독 UNIQUE는 없어야 한다(지시사항: source_id 단독 UNIQUE 사용 금지).
    assert frozenset({"source_id"}) not in unique_column_sets


def test_evidence_document_has_no_ingredient_fk_or_support_level_column() -> None:
    columns = EvidenceDocument.__table__.columns
    assert "ingredient_id" not in columns
    assert "support_level" not in columns


def test_evidence_document_uses_retrieved_at_not_collected_at() -> None:
    columns = EvidenceDocument.__table__.columns
    assert "retrieved_at" in columns
    assert "collected_at" not in columns
    assert columns["retrieved_at"].nullable is False


def test_evidence_chunk_document_fk_cascades() -> None:
    table = EvidenceChunk.__table__
    fk = next(iter(table.columns["document_id"].foreign_keys))
    assert fk.column.table.name == "evidence_document"
    assert fk.ondelete == "CASCADE"


def test_evidence_chunk_has_no_ingredient_fk_or_support_level_column() -> None:
    columns = EvidenceChunk.__table__.columns
    assert "ingredient_id" not in columns
    assert "support_level" not in columns


def test_evidence_chunk_vector_dimension_is_1024() -> None:
    # BAAI/bge-m3(local), 1024차원 - rag_chunk(text-embedding-3-small, 1536차원)와 별도 상수.
    embedding_column = EvidenceChunk.__table__.columns["embedding"]
    assert embedding_column.type.dim == 1024


def test_evidence_chunk_citation_locator_fields_are_independent_columns() -> None:
    """chunk_id 문자열 파싱이 아니라 독립 컬럼으로 citation을 조합할 수 있어야 한다."""
    columns = EvidenceChunk.__table__.columns
    for field in (
        "chunk_id",
        "document_id",
        "chunk_index",
        "page",
        "section",
        "content_hash",
        "parser_version",
        "source_type",
        "source_title",
        "url",
        "doi",
        "pmid",
        "jurisdiction",
    ):
        assert field in columns, f"citation provenance 컬럼 {field!r}이 없다"


def test_evidence_chunk_ingredient_has_composite_pk_and_cascades() -> None:
    table = evidence_chunk_ingredient
    pk_columns = {col.name for col in table.primary_key.columns}
    assert pk_columns == {"evidence_chunk_id", "ingredient_id"}

    chunk_fk = next(iter(table.columns["evidence_chunk_id"].foreign_keys))
    assert chunk_fk.column.table.name == "evidence_chunk"
    assert chunk_fk.ondelete == "CASCADE"

    ingredient_fk = next(iter(table.columns["ingredient_id"].foreign_keys))
    assert ingredient_fk.column.table.name == "ingredient_master"
    assert ingredient_fk.ondelete == "CASCADE"


def test_evidence_chunk_ingredient_pk_allows_multiple_ingredients_per_chunk() -> None:
    """PK가 (chunk_id, ingredient_id) 쌍이므로, 같은 chunk가 여러 ingredient_id 행을
    가질 수 있어야 한다(단일 chunk_id 단독 UNIQUE/PK가 아님 - 병용/충돌 근거 지원)."""
    table = evidence_chunk_ingredient
    pk_columns = {col.name for col in table.primary_key.columns}
    assert "evidence_chunk_id" in pk_columns
    assert len(pk_columns) > 1, "PK가 evidence_chunk_id 단독이면 성분 1개만 연결 가능해진다"


def test_evidence_migration_directly_follows_pre_evidence_head() -> None:
    """evidence 마이그레이션(11cdc111cf27) 자체가 d4c2a7e91b30 바로 다음 리비전인지만
    확인한다 - 전체 alembic head가 하나인지는 claim 마이그레이션까지 포함해
    test_claim_storage_schema.py가 담당한다(11cdc111cf27 위에 3165318c750d가 쌓였으므로
    이 파일 기준으로 "지금이 head"라고 단정하지 않는다)."""
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    evidence_revision = script.get_revision("11cdc111cf27")
    assert evidence_revision is not None
    assert evidence_revision.down_revision == "d4c2a7e91b30"
