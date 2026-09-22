"""`EvidenceDbWriteDryRun` 단위 테스트. 실제 DB 연결 없이 asyncpg 스텁으로 대체한다."""

import pytest

from data.scripts.evidence_db_write_dry_run import EvidenceDbWriteDryRun


class _FakeConn:
    def __init__(self, docs, chunks, links, ingredients, counts):
        self._docs = docs
        self._chunks = chunks
        self._links = links
        self._ingredients = ingredients
        self._counts = counts

    async def fetch(self, query, *args):
        if "FROM evidence_document" in query:
            return [{"source_type": s, "source_id": i} for s, i in self._docs]
        if "FROM evidence_chunk_ingredient" in query:
            return [{"chunk_id": c, "ingredient_id": i} for c, i in self._links]
        if "FROM evidence_chunk" in query:
            return [{"chunk_id": c} for c in self._chunks]
        if "FROM ingredient_master" in query:
            return [{"id": i} for i in self._ingredients]
        raise AssertionError(f"unexpected query: {query}")

    async def fetchval(self, query, *args):
        if "evidence_document" in query:
            return self._counts["evidence_document"]
        if "evidence_chunk_ingredient" in query:
            return self._counts["evidence_chunk_ingredient"]
        if "evidence_chunk" in query:
            return self._counts["evidence_chunk"]
        raise AssertionError(f"unexpected query: {query}")


def _doc_row(source_type, source_id, action):
    return {"source_type": source_type, "source_id": source_id, "action": action}


def _chunk_row(chunk_id, action):
    return {"chunk_id": chunk_id, "action": action}


def _link_row(chunk_id, ingredient_id, action):
    return {"chunk_id": chunk_id, "ingredient_id": ingredient_id, "action": action}


@pytest.mark.asyncio
async def test_clean_plan_has_no_mismatches():
    conn = _FakeConn(
        docs=[("pubmed_abstract", "PMID:1")],
        chunks=["PMID:1:abstract:0"],
        links=[("PMID:1:abstract:0", "ing-1")],
        ingredients=["ing-1", "ing-2"],
        counts={"evidence_document": 10, "evidence_chunk": 20, "evidence_chunk_ingredient": 30},
    )
    checker = EvidenceDbWriteDryRun(conn)

    documents = [
        _doc_row("pubmed_abstract", "PMID:1", "REUSE"),
        _doc_row("pubmed_abstract", "PMID:2", "INSERT"),
    ]
    chunks = [
        _chunk_row("PMID:1:abstract:0", "REUSE"),
        _chunk_row("PMID:2:abstract:0", "INSERT"),
    ]
    links = [
        _link_row("PMID:1:abstract:0", "ing-1", "EXISTS"),
        _link_row("PMID:2:abstract:0", "ing-2", "INSERT"),
    ]
    manifest = [{"chunk_id": "PMID:2:abstract:0"}]

    summary = await checker.run(documents, chunks, links, manifest)

    assert summary.mismatches == []
    assert summary.ready_for_db_write is True
    assert summary.row_deltas[0].after == 11  # document: +1 insert, 0 remove
    assert summary.row_deltas[1].after == 21
    assert summary.row_deltas[2].after == 31


@pytest.mark.asyncio
async def test_insert_target_already_existing_is_error():
    conn = _FakeConn(
        docs=[("pubmed_abstract", "PMID:1")],
        chunks=[],
        links=[],
        ingredients=[],
        counts={"evidence_document": 1, "evidence_chunk": 0, "evidence_chunk_ingredient": 0},
    )
    checker = EvidenceDbWriteDryRun(conn)

    summary = await checker.run(
        document_rows=[_doc_row("pubmed_abstract", "PMID:1", "INSERT")],
        chunk_rows=[],
        link_rows=[],
        manifest_rows=[],
    )

    assert summary.ready_for_db_write is False
    assert any("이미 동일" in m.reason for m in summary.mismatches)


@pytest.mark.asyncio
async def test_remove_target_missing_is_error():
    conn = _FakeConn(
        docs=[],
        chunks=[],
        links=[],
        ingredients=[],
        counts={"evidence_document": 0, "evidence_chunk": 0, "evidence_chunk_ingredient": 0},
    )
    checker = EvidenceDbWriteDryRun(conn)

    summary = await checker.run(
        document_rows=[_doc_row("pubmed_abstract", "PMID:1", "REMOVE")],
        chunk_rows=[],
        link_rows=[],
        manifest_rows=[],
    )

    assert summary.ready_for_db_write is False
    assert any("PK 없음" in m.reason for m in summary.mismatches)


@pytest.mark.asyncio
async def test_embedding_missing_target_is_error():
    conn = _FakeConn(
        docs=[],
        chunks=[],
        links=[],
        ingredients=[],
        counts={"evidence_document": 0, "evidence_chunk": 0, "evidence_chunk_ingredient": 0},
    )
    checker = EvidenceDbWriteDryRun(conn)

    summary = await checker.run(
        document_rows=[],
        chunk_rows=[_chunk_row("PMID:1:abstract:0", "INSERT")],
        link_rows=[],
        manifest_rows=[],
    )

    assert summary.embedding_missing == 1
    assert summary.ready_for_db_write is False


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
