# DB Write Dry-Run Report

## 범위

`FINAL_EVIDENCE_DB_ACTION_PLAN`(evidence_db_load_plan_documents/chunks/links.csv +
evidence_embedding_manifest.csv)을 canonical v4 DB(읽기 전용 임시 DB로 복원)와
대조했다. **실제 INSERT/UPDATE/DELETE는 전혀 실행하지 않았다** - `SELECT`만
수행했다. 추가 QA·lineage 재분석·PubMed/CIR 재수집은 하지 않았다(지시대로).

## 방법

- 기준 dump: `skincare_reference_2026-09-21_v4.dump`(alembic `9f4c2a7d8e61`)를
  별도 임시 DB(`evidence_dry_run_check`)에 복원해 조회했고, 확인 후 drop했다.
- 코드: `data/scripts/evidence_db_write_dry_run.py`(`EvidenceDbWriteDryRun`) +
  `data/scripts/evidence_db_write_dry_run_schemas.py`. `asyncpg`로 읽기 전용
  연결만 열어 대조했다.
- 실행: `uv run python -m data.scripts.evidence_db_write_dry_run --dsn <읽기 전용 DB DSN>`
- 단위 테스트: `tests/unit/test_evidence_db_write_dry_run.py`(4건, fake connection으로
  로직만 검증)

## 검증한 것

- **Document**: `INSERT` 대상이 canonical에 이미 있는지(있으면 오류), `REUSE`/
  `KEEP_IDENTITY`/`REMOVE`/`DEFER` 대상이 canonical에 실제로 존재하는지(PK 확인).
- **Chunk**: 동일한 방식으로 `chunk_id` PK 존재 여부 확인.
- **Link**: `ingredient_id`가 `ingredient_master`에 있는지(FK 확인), `EXISTS`/
  `REUSE`/`REMOVE` 대상이 canonical `evidence_chunk_ingredient`에 실제로 있는지,
  `INSERT` 대상 link가 참조하는 chunk가 canonical에 있거나 이번 plan의 chunk
  INSERT 목록 안에 있는지(신규 document의 신규 chunk에 붙는 link는 아직 canonical에
  chunk가 없는 게 정상이므로 이 경우도 함께 확인).
- **Embedding**: `evidence_embedding_manifest.csv`의 `chunk_id` 집합이 load plan의
  `action ∈ {INSERT, REPLACE}` 집합과 정확히 일치하는지(누락/중복/여분 확인).
- **Row delta**: `INSERT 수 - REMOVE 수`로 `evidence_document`/`evidence_chunk`/
  `evidence_chunk_ingredient`의 예상 증감을 canonical 현재 값에 더해 계산.

## 결과

```
DB_WRITE_DRY_RUN

Documents:
- insert: 86
- reuse: 15
- replace/update: 1 (KEEP_IDENTITY, PMID 16766489)
- remove: 6
- defer: 3

Chunks:
- insert: 122
- reuse: 15
- replace: 1
- remove: 6

Links:
- insert: 134
- reuse: 16 (EXISTS 12 + REUSE 4)
- remove: 7

Embeddings:
- insert/update targets: 123
- missing: 0
- duplicate: 0

Expected row delta:
- evidence_document: 46 -> 126 (+80)
- evidence_chunk: 8369 -> 8485 (+116)
- evidence_chunk_ingredient: 8377 -> 8504 (+127)

Mismatches: 없음(0건)
READY_FOR_DB_WRITE: YES
```

`FINAL_EVIDENCE_DB_ACTION_PLAN_REPORT.md`의 집계와 완전히 일치했다 - 모든
카테고리(document/chunk/link/embedding)에서 오차 0건.

## 판정

`READY_FOR_DB_WRITE: YES`

dry-run이 계획과 정확히 일치하고 PK/FK 미존재, 중복, embedding 누락 등 오류가
0건이다. 실제 DB write는 사용자 승인 후 별도 실행 경로로 진행한다(이 스크립트는
읽기 전용이라 그대로 재사용할 수 없고, INSERT/UPDATE/DELETE를 실제로 수행하는
스크립트는 아직 작성하지 않았다).
