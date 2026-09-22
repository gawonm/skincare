"""`FINAL_EVIDENCE_DB_ACTION_PLAN`(documents/chunks/links CSV + embedding manifest)을
읽기 전용으로 canonical DB와 대조하는 dry-run 진입점.

INSERT/UPDATE/DELETE를 전혀 실행하지 않는다 - `asyncpg`로 연결만 열고 `SELECT`만
수행한다. 실제 반영은 이 스크립트의 범위 밖이다(별도 승인 후 다른 실행 경로).

사용법:
    uv run python -m data.scripts.evidence_db_write_dry_run --dsn postgresql://app:app@localhost:5432/evidence_dry_run_check
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path

import asyncpg

from data.scripts.evidence_db_write_dry_run_schemas import (
    DryRunSummary,
    Mismatch,
    MismatchCategory,
    MismatchSeverity,
    RowDelta,
)

_DEFAULT_DOCUMENTS_PATH = Path("data/outputs/evidence_coverage/evidence_db_load_plan_documents.csv")
_DEFAULT_CHUNKS_PATH = Path("data/outputs/evidence_coverage/evidence_db_load_plan_chunks.csv")
_DEFAULT_LINKS_PATH = Path("data/outputs/evidence_coverage/evidence_db_load_plan_links.csv")
_DEFAULT_MANIFEST_PATH = Path("data/outputs/evidence_coverage/evidence_embedding_manifest.csv")

_INSERT_LIKE_DOC_ACTIONS = {"INSERT"}
_MUST_EXIST_DOC_ACTIONS = {"REUSE", "KEEP_IDENTITY", "REMOVE", "DEFER"}
_INSERT_LIKE_CHUNK_ACTIONS = {"INSERT"}
_MUST_EXIST_CHUNK_ACTIONS = {"REUSE", "REPLACE", "REMOVE", "DEFER"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class EvidenceDbWriteDryRun:
    """canonical DB(읽기 전용 connection)와 action plan CSV를 대조한다."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def _existing_document_keys(self) -> set[tuple[str, str]]:
        rows = await self._conn.fetch("SELECT source_type, source_id FROM evidence_document")
        return {(r["source_type"], r["source_id"]) for r in rows}

    async def _existing_chunk_ids(self) -> set[str]:
        rows = await self._conn.fetch("SELECT chunk_id FROM evidence_chunk")
        return {r["chunk_id"] for r in rows}

    async def _existing_link_keys(self) -> set[tuple[str, str]]:
        rows = await self._conn.fetch(
            "SELECT ec.chunk_id, eci.ingredient_id::text AS ingredient_id "
            "FROM evidence_chunk_ingredient eci "
            "JOIN evidence_chunk ec ON ec.id = eci.evidence_chunk_id"
        )
        return {(r["chunk_id"], r["ingredient_id"]) for r in rows}

    async def _existing_ingredient_ids(self) -> set[str]:
        rows = await self._conn.fetch("SELECT id::text AS id FROM ingredient_master")
        return {r["id"] for r in rows}

    async def _table_counts(self) -> dict[str, int]:
        doc_count = await self._conn.fetchval("SELECT count(*) FROM evidence_document")
        chunk_count = await self._conn.fetchval("SELECT count(*) FROM evidence_chunk")
        link_count = await self._conn.fetchval("SELECT count(*) FROM evidence_chunk_ingredient")
        return {
            "evidence_document": doc_count,
            "evidence_chunk": chunk_count,
            "evidence_chunk_ingredient": link_count,
        }

    async def run(
        self,
        document_rows: list[dict[str, str]],
        chunk_rows: list[dict[str, str]],
        link_rows: list[dict[str, str]],
        manifest_rows: list[dict[str, str]],
    ) -> DryRunSummary:
        mismatches: list[Mismatch] = []

        # ---------------- documents ----------------
        existing_docs = await self._existing_document_keys()
        doc_ids = [r["source_id"] for r in document_rows]
        if len(doc_ids) != len(set(doc_ids)):
            mismatches.append(
                Mismatch(
                    category=MismatchCategory.DOCUMENT,
                    key="(전체)",
                    action="-",
                    reason="load plan 안에 중복 source_id가 있다",
                    severity=MismatchSeverity.ERROR,
                )
            )
        documents_counter: dict[str, int] = {}
        for r in document_rows:
            documents_counter[r["action"]] = documents_counter.get(r["action"], 0) + 1
            key = (r["source_type"], r["source_id"])
            if r["action"] in _INSERT_LIKE_DOC_ACTIONS:
                if key in existing_docs:
                    mismatches.append(
                        Mismatch(
                            category=MismatchCategory.DOCUMENT,
                            key=r["source_id"],
                            action=r["action"],
                            reason="INSERT 대상인데 canonical에 이미 동일 (source_type, source_id)가 있다",
                            severity=MismatchSeverity.ERROR,
                        )
                    )
            elif r["action"] in _MUST_EXIST_DOC_ACTIONS and key not in existing_docs:
                mismatches.append(
                    Mismatch(
                        category=MismatchCategory.DOCUMENT,
                        key=r["source_id"],
                        action=r["action"],
                        reason=f"{r['action']} 대상인데 canonical에 해당 document가 없다(PK 없음)",
                        severity=MismatchSeverity.ERROR,
                    )
                )

        # ---------------- chunks ----------------
        existing_chunks = await self._existing_chunk_ids()
        chunk_ids = [r["chunk_id"] for r in chunk_rows]
        if len(chunk_ids) != len(set(chunk_ids)):
            mismatches.append(
                Mismatch(
                    category=MismatchCategory.CHUNK,
                    key="(전체)",
                    action="-",
                    reason="load plan 안에 중복 chunk_id가 있다",
                    severity=MismatchSeverity.ERROR,
                )
            )
        chunks_counter: dict[str, int] = {}
        insert_chunk_ids: set[str] = set()
        for r in chunk_rows:
            chunks_counter[r["action"]] = chunks_counter.get(r["action"], 0) + 1
            if r["action"] in _INSERT_LIKE_CHUNK_ACTIONS:
                insert_chunk_ids.add(r["chunk_id"])
                if r["chunk_id"] in existing_chunks:
                    mismatches.append(
                        Mismatch(
                            category=MismatchCategory.CHUNK,
                            key=r["chunk_id"],
                            action=r["action"],
                            reason="INSERT 대상인데 canonical에 이미 동일 chunk_id가 있다",
                            severity=MismatchSeverity.ERROR,
                        )
                    )
            elif r["action"] in _MUST_EXIST_CHUNK_ACTIONS and r["chunk_id"] not in existing_chunks:
                mismatches.append(
                    Mismatch(
                        category=MismatchCategory.CHUNK,
                        key=r["chunk_id"],
                        action=r["action"],
                        reason=f"{r['action']} 대상인데 canonical에 해당 chunk가 없다(PK 없음)",
                        severity=MismatchSeverity.ERROR,
                    )
                )

        # ---------------- links ----------------
        existing_links = await self._existing_link_keys()
        existing_ingredients = await self._existing_ingredient_ids()
        link_keys = [(r["chunk_id"], r["ingredient_id"]) for r in link_rows]
        if len(link_keys) != len(set(link_keys)):
            mismatches.append(
                Mismatch(
                    category=MismatchCategory.LINK,
                    key="(전체)",
                    action="-",
                    reason="load plan 안에 중복 (chunk_id, ingredient_id)가 있다",
                    severity=MismatchSeverity.ERROR,
                )
            )
        links_counter: dict[str, int] = {}
        for r in link_rows:
            links_counter[r["action"]] = links_counter.get(r["action"], 0) + 1
            key = (r["chunk_id"], r["ingredient_id"])
            if r["ingredient_id"] not in existing_ingredients:
                mismatches.append(
                    Mismatch(
                        category=MismatchCategory.LINK,
                        key=r["chunk_id"],
                        action=r["action"],
                        reason=f"ingredient_id {r['ingredient_id']}가 ingredient_master에 없다(FK 없음)",
                        severity=MismatchSeverity.ERROR,
                    )
                )
            if r["action"] == "INSERT":
                if key in existing_links:
                    mismatches.append(
                        Mismatch(
                            category=MismatchCategory.LINK,
                            key=r["chunk_id"],
                            action=r["action"],
                            reason="INSERT 대상인데 canonical에 이미 동일 link가 있다",
                            severity=MismatchSeverity.ERROR,
                        )
                    )
                elif r["chunk_id"] not in existing_chunks and r["chunk_id"] not in insert_chunk_ids:
                    mismatches.append(
                        Mismatch(
                            category=MismatchCategory.LINK,
                            key=r["chunk_id"],
                            action=r["action"],
                            reason=(
                                "이 link가 참조하는 chunk가 canonical에도 없고 "
                                "이번 plan의 chunk INSERT 목록에도 없다"
                            ),
                            severity=MismatchSeverity.ERROR,
                        )
                    )
            elif r["action"] in {"EXISTS", "REUSE", "REMOVE"} and key not in existing_links:
                mismatches.append(
                    Mismatch(
                        category=MismatchCategory.LINK,
                        key=r["chunk_id"],
                        action=r["action"],
                        reason=f"{r['action']} 대상인데 canonical evidence_chunk_ingredient에 없다",
                        severity=MismatchSeverity.ERROR,
                    )
                )

        # ---------------- embeddings ----------------
        embedding_targets = {r["chunk_id"] for r in manifest_rows}
        plan_embedding_targets = {
            r["chunk_id"] for r in chunk_rows if r["action"] in {"INSERT", "REPLACE"}
        }
        missing = plan_embedding_targets - embedding_targets
        extra = embedding_targets - plan_embedding_targets
        duplicate = len(manifest_rows) - len(embedding_targets)
        for chunk_id in sorted(missing):
            mismatches.append(
                Mismatch(
                    category=MismatchCategory.EMBEDDING,
                    key=chunk_id,
                    action="INSERT/REPLACE",
                    reason="load plan에는 embedding이 필요한데 manifest에 없다",
                    severity=MismatchSeverity.ERROR,
                )
            )
        for chunk_id in sorted(extra):
            mismatches.append(
                Mismatch(
                    category=MismatchCategory.EMBEDDING,
                    key=chunk_id,
                    action="-",
                    reason="manifest에는 있는데 load plan의 INSERT/REPLACE 대상이 아니다",
                    severity=MismatchSeverity.ERROR,
                )
            )
        if duplicate:
            mismatches.append(
                Mismatch(
                    category=MismatchCategory.EMBEDDING,
                    key="(전체)",
                    action="-",
                    reason=f"manifest에 chunk_id 중복이 {duplicate}건 있다",
                    severity=MismatchSeverity.ERROR,
                )
            )

        # ---------------- row delta ----------------
        before = await self._table_counts()
        doc_delta = documents_counter.get("INSERT", 0) - documents_counter.get("REMOVE", 0)
        chunk_delta = chunks_counter.get("INSERT", 0) - chunks_counter.get("REMOVE", 0)
        link_delta = links_counter.get("INSERT", 0) - links_counter.get("REMOVE", 0)
        row_deltas = [
            RowDelta(
                table="evidence_document",
                before=before["evidence_document"],
                delta=doc_delta,
                after=before["evidence_document"] + doc_delta,
            ),
            RowDelta(
                table="evidence_chunk",
                before=before["evidence_chunk"],
                delta=chunk_delta,
                after=before["evidence_chunk"] + chunk_delta,
            ),
            RowDelta(
                table="evidence_chunk_ingredient",
                before=before["evidence_chunk_ingredient"],
                delta=link_delta,
                after=before["evidence_chunk_ingredient"] + link_delta,
            ),
        ]

        return DryRunSummary(
            documents=documents_counter,
            chunks=chunks_counter,
            links=links_counter,
            embedding_insert_update_targets=len(embedding_targets),
            embedding_missing=len(missing),
            embedding_duplicate=duplicate,
            row_deltas=row_deltas,
            mismatches=mismatches,
        )


async def _run(
    *,
    dsn: str,
    documents_path: Path,
    chunks_path: Path,
    links_path: Path,
    manifest_path: Path,
) -> DryRunSummary:
    document_rows = _read_csv(documents_path)
    chunk_rows = _read_csv(chunks_path)
    link_rows = _read_csv(links_path)
    manifest_rows = _read_csv(manifest_path)

    conn = await asyncpg.connect(dsn)
    try:
        checker = EvidenceDbWriteDryRun(conn)
        return await checker.run(document_rows, chunk_rows, link_rows, manifest_rows)
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        required=True,
        help="읽기 전용으로 조회할 canonical DB 연결 문자열(예: postgresql://app:app@localhost:5432/<db>)",
    )
    parser.add_argument("--documents-path", type=Path, default=_DEFAULT_DOCUMENTS_PATH)
    parser.add_argument("--chunks-path", type=Path, default=_DEFAULT_CHUNKS_PATH)
    parser.add_argument("--links-path", type=Path, default=_DEFAULT_LINKS_PATH)
    parser.add_argument("--manifest-path", type=Path, default=_DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()

    summary = asyncio.run(
        _run(
            dsn=args.dsn,
            documents_path=args.documents_path,
            chunks_path=args.chunks_path,
            links_path=args.links_path,
            manifest_path=args.manifest_path,
        )
    )
    payload = summary.model_dump(mode="json")
    payload["ready_for_db_write"] = summary.ready_for_db_write
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
