"""legacy `evidence`(MFDS 8,288건)를 `evidence_document`/`evidence_chunk` 신규 저장소로
옮기는 재현 가능한 ingestion 파이프라인 진입점.

`evidence_chunk.embedding`이 `vector(1024) NOT NULL`이라 이 스크립트는 임베딩 없이
`evidence_chunk` 행을 만들 수 없다 - 그래서 이 단계는 `evidence_document`만 DB에
적재하고(임베딩 의존성 없음), `evidence_chunk`가 될 내용은 JSONL 스테이징 파일로만
써 둔다. 실제 `evidence_chunk` INSERT는 이후 BAAI/bge-m3 임베딩 단계 스크립트가 이
스테이징 파일을 읽어 수행한다(이 스크립트 범위 밖).

기본 동작은 dry-run이다 - `--execute`를 명시해야 `evidence_document`에 실제로 쓴다
(지시사항 "live DB 기본 실행 금지"). dry-run은 legacy `evidence`를 읽기만 하고 어떤
테이블에도 쓰지 않는다.

재실행 안전성:
    - `evidence_document`는 `(source_type, source_id)` UNIQUE 기준 get-or-create라
      몇 번을 다시 실행해도 jurisdiction당 문서 1건만 남는다.
    - chunk 스테이징 JSONL은 매번 legacy `evidence`에서 처음부터 결정적으로 재계산해
      통째로 다시 쓴다(NIA production runner와 달리 이 단계는 LLM을 호출하지 않아
      "일부만 계산된 상태"가 생길 수 없다 - `docs/data/README.md` 증분저장 교훈과는
      해당사항이 다름).

사용법:
    uv run python -m data.scripts.mfds_evidence_backfill                # dry-run(기본)
    uv run python -m data.scripts.mfds_evidence_backfill --limit 50      # dry-run + 소량
    uv run python -m data.scripts.mfds_evidence_backfill --execute       # evidence_document 실제 적재
"""

import argparse
import asyncio
import csv
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import Database
from data.scripts.mfds_evidence_backfill_schemas import (
    EvidenceDocumentPlan,
    LegacyEvidenceRow,
    MfdsEvidenceBackfillSummary,
)
from data.scripts.mfds_evidence_mapper import MfdsEvidenceMapper
from models.evidence import Evidence, EvidenceSourceType
from models.evidence_document import EvidenceDocument

_DEFAULT_STAGING_PATH = Path("data/processed/mfds_evidence_chunk_staging.jsonl")
_DEFAULT_FAILURE_QUEUE_PATH = Path("data/manual_review/mfds_evidence_backfill_failures.csv")
_FAILURE_QUEUE_HEADER = ("legacy_evidence_id", "reason")


async def _load_legacy_rows(session: AsyncSession, limit: int | None) -> list[LegacyEvidenceRow]:
    query = (
        select(Evidence)
        .where(Evidence.source_type == EvidenceSourceType.MFDS_RESTRICTED_INGREDIENT)
        .order_by(Evidence.id)
    )
    if limit is not None:
        query = query.limit(limit)
    result = await session.execute(query)
    return [
        LegacyEvidenceRow(
            id=row.id,
            ingredient_id=row.ingredient_id,
            claim=row.claim,
            conditions=row.conditions,
            jurisdiction=row.jurisdiction,
            regulate_type=row.regulate_type.value if row.regulate_type else None,
            cas_no=row.cas_no,
            ingredient_synonym=row.ingredient_synonym,
            notice_ingredient_name=row.notice_ingredient_name,
            source_title=row.source_title,
            source_url=row.source_url,
            collected_at=row.collected_at,
        )
        for row in result.scalars().all()
    ]


async def _upsert_documents(
    session: AsyncSession, plans: list[EvidenceDocumentPlan]
) -> tuple[int, int]:
    """`(source_type, source_id)` 기준 get-or-create. commit은 호출한 쪽이 한다."""
    inserted = 0
    already_existed = 0
    for plan in plans:
        existing = await session.execute(
            select(EvidenceDocument.id).where(
                EvidenceDocument.source_type == plan.source_type,
                EvidenceDocument.source_id == plan.source_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            already_existed += 1
            continue
        session.add(
            EvidenceDocument(
                source_id=plan.source_id,
                source_type=plan.source_type,
                source_title=plan.source_title,
                publisher=None,
                document_date=None,
                url=plan.url,
                doi=None,
                pmid=None,
                jurisdiction=plan.jurisdiction,
                language=plan.language,
                evidence_level=plan.evidence_level,
                raw_ingredient_names=plan.raw_ingredient_names,
                document_status=None,
                study_type=None,
                formulation_type=None,
                claim_topics=[topic.value for topic in plan.claim_topics],
                retrieved_at=plan.retrieved_at,
            )
        )
        inserted += 1
    return inserted, already_existed


def _write_staging_jsonl(records: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as jsonl_file:
        for record in records:
            jsonl_file.write(record.model_dump_json())
            jsonl_file.write("\n")


def _write_failure_queue(failures: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(_FAILURE_QUEUE_HEADER)
        for failure in failures:
            writer.writerow((str(failure.legacy_evidence_id), failure.reason))


async def _run(
    *, execute: bool, limit: int | None, staging_path: Path, failure_queue_path: Path
) -> MfdsEvidenceBackfillSummary:
    database = Database(settings.database)
    mapper = MfdsEvidenceMapper()
    try:
        async with database.session_factory() as session:
            legacy_rows = await _load_legacy_rows(session, limit)
            valid_rows, failures = mapper.partition_valid_rows(legacy_rows)
            document_plans = mapper.build_documents(valid_rows)
            chunk_records = mapper.build_chunks(valid_rows)

            documents_inserted = 0
            documents_already_existed = 0
            if execute:
                documents_inserted, documents_already_existed = await _upsert_documents(
                    session, document_plans
                )
                await session.commit()

        _write_staging_jsonl(chunk_records, staging_path)
        if failures:
            _write_failure_queue(failures, failure_queue_path)

        return MfdsEvidenceBackfillSummary(
            dry_run=not execute,
            total_legacy_rows=len(legacy_rows),
            documents_planned=len(document_plans),
            chunks_planned=len(chunk_records),
            failures=len(failures),
            documents_inserted=documents_inserted,
            documents_already_existed=documents_already_existed,
        )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="evidence_document에 실제로 쓴다. 기본은 dry-run(읽기 전용)이다.",
    )
    parser.add_argument("--limit", type=int, default=None, help="처리할 legacy row 수 제한")
    parser.add_argument(
        "--staging-path",
        type=Path,
        default=_DEFAULT_STAGING_PATH,
        help=f"chunk 스테이징 JSONL 경로 (기본값: {_DEFAULT_STAGING_PATH})",
    )
    parser.add_argument(
        "--failure-queue-path",
        type=Path,
        default=_DEFAULT_FAILURE_QUEUE_PATH,
        help=f"실패 큐 CSV 경로 (기본값: {_DEFAULT_FAILURE_QUEUE_PATH})",
    )
    args = parser.parse_args()

    summary = asyncio.run(
        _run(
            execute=args.execute,
            limit=args.limit,
            staging_path=args.staging_path,
            failure_queue_path=args.failure_queue_path,
        )
    )
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
