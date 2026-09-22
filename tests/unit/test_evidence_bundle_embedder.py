"""`EvidenceBundleEmbedder` 단위 테스트. 실제 BGE-M3 모델은 로드하지 않고
`MfdsEvidenceEmbedder.embed_texts`만 mock으로 대체한다."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from data.scripts.evidence_bundle_embedder import EvidenceBundleEmbedder
from data.scripts.evidence_bundle_embedding_schemas import EvidenceEmbeddingAction
from data.scripts.mfds_evidence_embedder import MfdsEvidenceEmbeddingResult

_DIM = 1024


def _write_chunks(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_load_plan(path: Path, actions: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("chunk_id,action\n")
        for chunk_id, action in actions.items():
            f.write(f"{chunk_id},{action}\n")


class TestLoadTargets:
    def test_skips_reuse_and_keeps_insert_and_replace(self, tmp_path: Path) -> None:
        chunks_path = tmp_path / "chunks.jsonl"
        plan_path = tmp_path / "plan.csv"
        _write_chunks(
            chunks_path,
            [
                {
                    "chunk_id": "a",
                    "source_type": "pubmed_abstract",
                    "document_source_id": "PMID:1",
                    "content": "hello",
                    "content_hash": "h1",
                },
                {
                    "chunk_id": "b",
                    "source_type": "pubmed_abstract",
                    "document_source_id": "PMID:2",
                    "content": "world",
                    "content_hash": "h2",
                },
                {
                    "chunk_id": "c",
                    "source_type": "pubmed_abstract",
                    "document_source_id": "PMID:3",
                    "content": "reused",
                    "content_hash": "h3",
                },
            ],
        )
        _write_load_plan(plan_path, {"a": "INSERT", "b": "REPLACE", "c": "REUSE"})

        targets, reused_skipped = EvidenceBundleEmbedder.load_targets(chunks_path, plan_path)

        assert reused_skipped == 1
        assert [t.chunk_id for t in targets] == ["a", "b"]
        assert targets[0].action is EvidenceEmbeddingAction.INSERT
        assert targets[1].action is EvidenceEmbeddingAction.REPLACE

    def test_missing_chunk_id_in_load_plan_raises(self, tmp_path: Path) -> None:
        chunks_path = tmp_path / "chunks.jsonl"
        plan_path = tmp_path / "plan.csv"
        _write_chunks(
            chunks_path,
            [
                {
                    "chunk_id": "unknown",
                    "source_type": "cir",
                    "document_source_id": "cir_attachment:x",
                    "content": "x",
                    "content_hash": "hx",
                }
            ],
        )
        _write_load_plan(plan_path, {})

        with pytest.raises(ValueError, match="unknown"):
            EvidenceBundleEmbedder.load_targets(chunks_path, plan_path)


class TestEmbedAndValidate:
    @pytest.mark.asyncio
    async def test_validation_passes_for_clean_targets(self, tmp_path: Path) -> None:
        chunks_path = tmp_path / "chunks.jsonl"
        plan_path = tmp_path / "plan.csv"
        _write_chunks(
            chunks_path,
            [
                {
                    "chunk_id": "a",
                    "source_type": "pubmed_abstract",
                    "document_source_id": "PMID:1",
                    "content": "hello",
                    "content_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                },
            ],
        )
        _write_load_plan(plan_path, {"a": "INSERT"})
        targets, reused_skipped = EvidenceBundleEmbedder.load_targets(chunks_path, plan_path)
        # 실제 sha256("hello")로 content_hash를 맞춰 둔다
        import hashlib

        object.__setattr__(targets[0], "content_hash", hashlib.sha256(b"hello").hexdigest())

        fake_embedder = AsyncMock()
        fake_embedder.embed_texts.return_value = MfdsEvidenceEmbeddingResult(
            model="BAAI/bge-m3", vectors=[[0.1] * _DIM]
        )
        embedder = EvidenceBundleEmbedder(fake_embedder)
        records = await embedder.embed_targets(targets)
        validation = EvidenceBundleEmbedder.validate(targets, records, reused_skipped)

        assert validation.targets == 1
        assert validation.model == "BAAI/bge-m3"
        assert validation.dimension_ok is True
        assert validation.content_hash_preserved is True
        assert validation.chunk_id_one_to_one is True
        assert validation.duplicate_targets == 0
        assert validation.missing_embeddings == 0

    @pytest.mark.asyncio
    async def test_missing_embedding_detected(self, tmp_path: Path) -> None:
        chunks_path = tmp_path / "chunks.jsonl"
        plan_path = tmp_path / "plan.csv"
        _write_chunks(
            chunks_path,
            [
                {
                    "chunk_id": "a",
                    "source_type": "cir",
                    "document_source_id": "cir_attachment:x",
                    "content": "hello",
                    "content_hash": "irrelevant",
                },
            ],
        )
        _write_load_plan(plan_path, {"a": "INSERT"})
        targets, reused_skipped = EvidenceBundleEmbedder.load_targets(chunks_path, plan_path)

        validation = EvidenceBundleEmbedder.validate(
            targets, records=[], reused_skipped=reused_skipped
        )

        assert validation.missing_embeddings == 1
        assert validation.chunk_id_one_to_one is False


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
