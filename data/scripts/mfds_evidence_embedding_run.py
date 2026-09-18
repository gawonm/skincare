"""PR #33 chunk staging JSONL을 읽어 BGE-M3로 임베딩하고 `evidence_chunk`/
`evidence_chunk_ingredient`에 적재하는 진입점.

기본 동작은 dry-run이다 - `--execute`를 명시해야 실제로 DB에 쓴다(지시사항
"live DB 기본 실행 금지", PR #33과 같은 관례). dry-run은 staging 파일을 읽고 이미
적재된 chunk_id를 건너뛰는 계획까지만 계산하고, 임베딩 모델을 로드하지도 DB에 쓰지도
않는다.

재실행 안전성: `evidence_chunk.chunk_id`의 기존 UNIQUE 제약으로 이미 적재된 chunk는
건너뛴다(`mfds_evidence_chunk_loader.py` 참고) - 중단된 지점부터 이어서 실행하면 된다.

사용법:
    uv run python -m data.scripts.mfds_evidence_embedding_run                # dry-run(기본)
    uv run python -m data.scripts.mfds_evidence_embedding_run --limit 5      # dry-run + 소량
    uv run python -m data.scripts.mfds_evidence_embedding_run --limit 5 --execute  # 실제 적재
"""

import argparse
import asyncio
import csv
import json
from pathlib import Path

from core.config import settings
from core.database import Database
from data.scripts.mfds_evidence_backfill_schemas import EvidenceChunkStagingRecord
from data.scripts.mfds_evidence_chunk_loader import MfdsEvidenceChunkLoader
from data.scripts.mfds_evidence_embedder import MfdsEvidenceEmbedder
from data.scripts.mfds_evidence_embedding_pipeline import (
    DEFAULT_COMMIT_BATCH_SIZE,
    MfdsEvidenceEmbeddingPipeline,
)

_DEFAULT_STAGING_PATH = Path("data/processed/mfds_evidence_chunk_staging.jsonl")
_DEFAULT_FAILURE_QUEUE_PATH = Path("data/manual_review/mfds_evidence_embedding_failures.csv")
_FAILURE_QUEUE_HEADER = ("chunk_id", "legacy_evidence_id", "reason", "retryable")


def _load_staging_records(path: Path, limit: int | None) -> list[EvidenceChunkStagingRecord]:
    if not path.exists():
        raise RuntimeError(
            f"chunk 스테이징 파일이 없습니다: {path}. "
            "먼저 `python -m data.scripts.mfds_evidence_backfill`을 실행하세요."
        )
    records: list[EvidenceChunkStagingRecord] = []
    with path.open("r", encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            line = line.strip()
            if not line:
                continue
            records.append(EvidenceChunkStagingRecord.model_validate_json(line))
            if limit is not None and len(records) >= limit:
                break
    return records


def _write_failure_queue(failures: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(_FAILURE_QUEUE_HEADER)
        for failure in failures:
            writer.writerow(
                (failure.chunk_id, str(failure.legacy_evidence_id), failure.reason, failure.retryable)
            )


async def _run(
    *,
    execute: bool,
    limit: int | None,
    staging_path: Path,
    failure_queue_path: Path,
    commit_batch_size: int,
) -> dict[str, object]:
    records = _load_staging_records(staging_path, limit)

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            loader = MfdsEvidenceChunkLoader(session)
            embedder = MfdsEvidenceEmbedder(settings.agent.embedding)
            pipeline = MfdsEvidenceEmbeddingPipeline(
                embedder, loader, commit_batch_size=commit_batch_size
            )
            summary, failures = await pipeline.run(records, dry_run=not execute)
            if execute:
                await session.commit()
    finally:
        await database.dispose()

    if failures:
        _write_failure_queue(failures, failure_queue_path)

    return summary.model_dump(mode="json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="evidence_chunk/evidence_chunk_ingredient에 실제로 쓴다. 기본은 dry-run이다.",
    )
    parser.add_argument("--limit", type=int, default=None, help="처리할 staging record 수 제한")
    parser.add_argument("--staging-path", type=Path, default=_DEFAULT_STAGING_PATH)
    parser.add_argument("--failure-queue-path", type=Path, default=_DEFAULT_FAILURE_QUEUE_PATH)
    parser.add_argument(
        "--commit-batch-size",
        type=int,
        default=DEFAULT_COMMIT_BATCH_SIZE,
        help=f"임베딩/삽입 배치 크기 (기본값: {DEFAULT_COMMIT_BATCH_SIZE})",
    )
    args = parser.parse_args()

    summary = asyncio.run(
        _run(
            execute=args.execute,
            limit=args.limit,
            staging_path=args.staging_path,
            failure_queue_path=args.failure_queue_path,
            commit_batch_size=args.commit_batch_size,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
