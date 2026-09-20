"""Claim 저장 구조(claim_document/claim_chunk/claim_chunk_ingredient) 검증.

metadata(컬럼/제약/FK 선언)와 alembic head를 Python 레벨에서 검증한다. 실제 DB 제약 동작
(version coexistence, roundtrip, ingredient linkage insert)은 tests/db/
test_claim_storage_migration.py에서 확인한다(live 미적용 상태라 CI/로컬 기본 실행에는 포함되지
않음 - 별도 DB로 검증 완료, `docs/data/CLAIM_STORAGE_ERD.md` 참고).
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from core.database import Base
from models.claim_chunk import ClaimChunk, claim_chunk_ingredient
from models.claim_document import ClaimDocument

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_claim_tables_registered_in_metadata() -> None:
    assert "claim_document" in Base.metadata.tables
    assert "claim_chunk" in Base.metadata.tables
    assert "claim_chunk_ingredient" in Base.metadata.tables


def test_claim_document_has_composite_unique_record_annotation() -> None:
    table = ClaimDocument.__table__
    unique_column_sets = {
        frozenset(col.name for col in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert frozenset({"source_record_id", "annotation_version"}) in unique_column_sets
    # 단일 source_record_id 단독 UNIQUE는 없어야 한다 - 같은 레코드가 여러 annotation run에서
    # 재라벨링되는 걸 막으면 안 된다(2026-09-17 결정).
    assert frozenset({"source_record_id"}) not in unique_column_sets


def test_claim_chunk_document_fk_cascades() -> None:
    table = ClaimChunk.__table__
    fk = next(iter(table.columns["claim_document_id"].foreign_keys))
    assert fk.column.table.name == "claim_document"
    assert fk.ondelete == "CASCADE"


def test_claim_chunk_has_composite_unique_document_statement_not_bare_statement_id() -> None:
    """statement_id는 annotation run마다 재사용되므로(S001, S002, ... 재부여, 실측 확인)
    claim_document_id와 묶어야 유일 - 단독 UNIQUE면 안 된다."""
    table = ClaimChunk.__table__
    unique_column_sets = {
        frozenset(col.name for col in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert frozenset({"claim_document_id", "statement_id"}) in unique_column_sets
    assert frozenset({"statement_id"}) not in unique_column_sets


def test_claim_chunk_vector_dimension_is_1024() -> None:
    # BAAI/bge-m3(local), 1024차원 - evidence_chunk와 같은 결정(rag_chunk의 1536과는 별도).
    embedding_column = ClaimChunk.__table__.columns["embedding"]
    assert embedding_column.type.dim == 1024


def test_claim_chunk_preserves_all_frozen_claimdocument_fields() -> None:
    """FROZEN ClaimDocument(Pydantic, data/scripts/nia_claim_document.py)의 8개 필드가
    claim_document/claim_chunk 어딘가에 전부 존재하는지 확인한다(정보 손실 없음,
    CLAIM_STORAGE_CROSS_SESSION_REVIEW 결과)."""
    chunk_columns = set(ClaimChunk.__table__.columns.keys())
    document_columns = set(ClaimDocument.__table__.columns.keys())

    # statement 단위 필드 -> claim_chunk
    for field in (
        "statement_id",
        "statement_type",
        "content",
        "source_spans",
        "decision",
        "priority",
        "support_status",
    ):
        assert field in chunk_columns, f"ClaimDocument 필드 {field!r}가 claim_chunk에 없다"

    # 레코드 단위 필드(record 내 모든 statement가 동일값, mapper 코드로 확인됨) -> claim_document
    for field in ("schema_version", "dataset_split", "skin_concerns_raw", "source_record_id"):
        assert field in document_columns, f"ClaimDocument 필드 {field!r}가 claim_document에 없다"

    # ingredient_refs는 claim_chunk_ingredient(별도 테이블)로 - 여기서는 존재만 확인
    ingredient_columns = set(claim_chunk_ingredient.columns.keys())
    for field in ("ingredient_id", "raw_name", "matching_status", "role"):
        assert field in ingredient_columns, (
            f"IngredientRef 필드 {field!r}가 claim_chunk_ingredient에 없다"
        )


def test_claim_chunk_ingredient_allows_null_ingredient_id_with_check_constraint() -> None:
    """evidence_chunk_ingredient와 달리 ingredient_id가 NULL일 수 있다(unresolved raw_name-only
    케이스, FROZEN IngredientRef가 허용) - 그래서 복합 PK가 아니라 서러게이트 PK + CHECK다."""
    table = claim_chunk_ingredient
    assert table.columns["ingredient_id"].nullable is True
    assert table.columns["raw_name"].nullable is True

    pk_columns = {col.name for col in table.primary_key.columns}
    assert pk_columns == {"id"}, "ingredient_id가 nullable이므로 복합 PK를 쓸 수 없다"

    check_sqls = {
        c.sqltext.text if hasattr(c.sqltext, "text") else str(c.sqltext)
        for c in table.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert any("ingredient_id IS NOT NULL OR raw_name IS NOT NULL" in sql for sql in check_sqls)


def test_claim_chunk_ingredient_fks_cascade() -> None:
    table = claim_chunk_ingredient
    chunk_fk = next(iter(table.columns["claim_chunk_id"].foreign_keys))
    assert chunk_fk.column.table.name == "claim_chunk"
    assert chunk_fk.ondelete == "CASCADE"

    ingredient_fk = next(iter(table.columns["ingredient_id"].foreign_keys))
    assert ingredient_fk.column.table.name == "ingredient_master"
    assert ingredient_fk.ondelete == "CASCADE"


def test_claim_chunk_has_no_matched_ingredient_unique_constraint_yet() -> None:
    """matched ingredient 중복 방지 unique constraint는 실제 데이터 중복 패턴을 먼저 확인한
    뒤 적용하기로 결정됨(2026-09-17) - 지금은 없어야 한다."""
    table = claim_chunk_ingredient
    unique_like = [c for c in table.constraints if c.__class__.__name__ in ("UniqueConstraint",)]
    assert unique_like == []


def test_alembic_single_head_keeps_claim_and_nia_case_migration_chain() -> None:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"단일 head가 아니다: {heads}"

    head_revision = script.get_revision(heads[0])
    assert head_revision is not None
    assert head_revision.revision == "a7d3c91e5f42"
    assert head_revision.down_revision == "3165318c750d"

    claim_revision = script.get_revision("3165318c750d")
    assert claim_revision is not None
    assert claim_revision.down_revision == "11cdc111cf27"
