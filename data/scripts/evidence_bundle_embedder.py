"""combined evidence bundle(PubMed+CIR) 중 INSERT/REPLACE 대상 chunk만 BGE-M3로
임베딩하는 진입점.

`evidence_db_load_plan_chunks.csv`의 `action=REUSE`(canonical과 content_hash가 이미
동일한 11건)는 재임베딩하지 않는다 - canonical `evidence_chunk.embedding`을 그대로
쓸 수 있기 때문이다. 이 스크립트는 DB 세션을 전혀 열지 않는다: canonical DB write는
별도 승인 전까지 하지 않는다는 지시에 따라, 결과는 로컬 벡터 JSONL + 경량 manifest
CSV로만 남긴다.

사용법:
    uv run python -m data.scripts.evidence_bundle_embedder
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
from pathlib import Path

from core.config import settings
from data.scripts.evidence_bundle_embedding_schemas import (
    EvidenceChunkEmbeddingTarget,
    EvidenceEmbeddingAction,
    EvidenceEmbeddingManifestRow,
    EvidenceEmbeddingRecord,
    EvidenceEmbeddingValidation,
)
from data.scripts.mfds_evidence_embedder import MfdsEvidenceEmbedder

_DEFAULT_CHUNKS_PATH = Path("data/outputs/evidence_coverage/combined_evidence_chunks.jsonl")
_DEFAULT_LOAD_PLAN_PATH = Path("data/outputs/evidence_coverage/evidence_db_load_plan_chunks.csv")
_DEFAULT_VECTORS_PATH = Path("data/outputs/evidence_coverage/embeddings/evidence_embeddings.jsonl")
_DEFAULT_MANIFEST_PATH = Path("data/outputs/evidence_coverage/evidence_embedding_manifest.csv")

_EMBEDDING_ACTIONS = {EvidenceEmbeddingAction.INSERT, EvidenceEmbeddingAction.REPLACE}


class EvidenceBundleEmbedder:
    """load plan action 기준으로 대상을 골라 embed하고 벡터/manifest를 만든다."""

    def __init__(self, embedder: MfdsEvidenceEmbedder) -> None:
        self._embedder = embedder

    @staticmethod
    def load_targets(
        chunks_path: Path, load_plan_path: Path
    ) -> tuple[list[EvidenceChunkEmbeddingTarget], int]:
        """번들 chunk와 load plan action을 합쳐 임베딩 대상만 추린다.

        반환값은 (대상 목록, REUSE라서 건너뛴 건수)다.
        """
        actions: dict[str, str] = {}
        with load_plan_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                actions[row["chunk_id"]] = row["action"]

        targets: list[EvidenceChunkEmbeddingTarget] = []
        reused_skipped = 0
        with chunks_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                chunk = json.loads(line)
                action = actions.get(chunk["chunk_id"])
                if action is None:
                    raise ValueError(f"load plan에 없는 chunk_id입니다: {chunk['chunk_id']}")
                if action not in _EMBEDDING_ACTIONS:
                    reused_skipped += 1
                    continue
                targets.append(
                    EvidenceChunkEmbeddingTarget(
                        chunk_id=chunk["chunk_id"],
                        source_type=chunk["source_type"],
                        document_source_id=chunk["document_source_id"],
                        content=chunk["content"],
                        content_hash=chunk["content_hash"],
                        action=EvidenceEmbeddingAction(action),
                    )
                )
        return targets, reused_skipped

    async def embed_targets(
        self, targets: list[EvidenceChunkEmbeddingTarget]
    ) -> list[EvidenceEmbeddingRecord]:
        result = await self._embedder.embed_texts([t.content for t in targets])
        return [
            EvidenceEmbeddingRecord(
                chunk_id=target.chunk_id,
                model=result.model,
                dimension=len(vector),
                content_hash=target.content_hash,
                vector=vector,
            )
            for target, vector in zip(targets, result.vectors, strict=True)
        ]

    @staticmethod
    def validate(
        targets: list[EvidenceChunkEmbeddingTarget],
        records: list[EvidenceEmbeddingRecord],
        reused_skipped: int,
    ) -> EvidenceEmbeddingValidation:
        chunk_ids = [t.chunk_id for t in targets]
        duplicate_targets = len(chunk_ids) - len(set(chunk_ids))

        records_by_chunk = {r.chunk_id: r for r in records}
        missing = 0
        content_hash_preserved = True
        dimension_ok = True
        for target in targets:
            record = records_by_chunk.get(target.chunk_id)
            if record is None:
                missing += 1
                continue
            recomputed_hash = hashlib.sha256(target.content.encode("utf-8")).hexdigest()
            if recomputed_hash != target.content_hash or record.content_hash != target.content_hash:
                content_hash_preserved = False
            if record.dimension != 1024:
                dimension_ok = False

        models = {r.model for r in records}
        model = models.pop() if len(models) == 1 else "MIXED"

        return EvidenceEmbeddingValidation(
            targets=len(targets),
            reused_skipped=reused_skipped,
            model=model,
            dimension_ok=dimension_ok,
            content_hash_preserved=content_hash_preserved,
            chunk_id_one_to_one=(duplicate_targets == 0 and len(records) == len(targets)),
            duplicate_targets=duplicate_targets,
            missing_embeddings=missing,
        )

    @staticmethod
    def write_outputs(
        targets: list[EvidenceChunkEmbeddingTarget],
        records: list[EvidenceEmbeddingRecord],
        vectors_path: Path,
        manifest_path: Path,
    ) -> None:
        vectors_path.parent.mkdir(parents=True, exist_ok=True)
        with vectors_path.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(record.model_dump_json())
                f.write("\n")

        targets_by_chunk = {t.chunk_id: t for t in targets}
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8", newline="") as f:
            fieldnames = list(EvidenceEmbeddingManifestRow.model_fields.keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                target = targets_by_chunk[record.chunk_id]
                vector_sha256 = hashlib.sha256(
                    ",".join(f"{v:.8f}" for v in record.vector).encode("utf-8")
                ).hexdigest()
                l2_norm = math.sqrt(sum(v * v for v in record.vector))
                row = EvidenceEmbeddingManifestRow(
                    chunk_id=record.chunk_id,
                    source_type=target.source_type,
                    document_source_id=target.document_source_id,
                    action=target.action,
                    model=record.model,
                    dimension=record.dimension,
                    content_hash=record.content_hash,
                    vector_sha256=vector_sha256,
                    vector_l2_norm=round(l2_norm, 6),
                )
                writer.writerow(row.model_dump(mode="json"))


async def _run(
    *,
    chunks_path: Path,
    load_plan_path: Path,
    vectors_path: Path,
    manifest_path: Path,
) -> EvidenceEmbeddingValidation:
    targets, reused_skipped = EvidenceBundleEmbedder.load_targets(chunks_path, load_plan_path)
    embedder = EvidenceBundleEmbedder(MfdsEvidenceEmbedder(settings.agent.embedding))
    records = await embedder.embed_targets(targets)
    validation = EvidenceBundleEmbedder.validate(targets, records, reused_skipped)
    EvidenceBundleEmbedder.write_outputs(targets, records, vectors_path, manifest_path)
    return validation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks-path", type=Path, default=_DEFAULT_CHUNKS_PATH)
    parser.add_argument("--load-plan-path", type=Path, default=_DEFAULT_LOAD_PLAN_PATH)
    parser.add_argument("--vectors-path", type=Path, default=_DEFAULT_VECTORS_PATH)
    parser.add_argument("--manifest-path", type=Path, default=_DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()

    validation = asyncio.run(
        _run(
            chunks_path=args.chunks_path,
            load_plan_path=args.load_plan_path,
            vectors_path=args.vectors_path,
            manifest_path=args.manifest_path,
        )
    )
    print(json.dumps(validation.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
