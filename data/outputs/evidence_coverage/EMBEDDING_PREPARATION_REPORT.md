# Embedding Preparation Report

## 범위

combined evidence bundle의 chunk 중 `evidence_db_load_plan_chunks.csv`
`action`이 `INSERT`(122) 또는 `REPLACE`(1)인 123건만 BGE-M3로 임베딩했다.
`action=REUSE`(11)는 canonical `evidence_chunk.embedding`을 그대로 쓸 수
있으므로 재계산하지 않았다. **canonical DB write는 이번 단계에서도 하지
않았다** — 결과는 로컬 산출물로만 남겼다.

## 실행

- 코드: `data/scripts/evidence_bundle_embedder.py`(`EvidenceBundleEmbedder`) +
  `data/scripts/evidence_bundle_embedding_schemas.py`. 기존 `MfdsEvidenceEmbedder`
  (`data/scripts/mfds_evidence_embedder.py`)를 그대로 재사용해 새 임베딩 코드를
  중복 작성하지 않았다.
- 실행: `uv run python -m data.scripts.evidence_bundle_embedder`
- 단위 테스트: `tests/unit/test_evidence_bundle_embedder.py`(4건, 실제 모델 로드 없이
  대상 선정/검증 로직만 mock으로 확인)

## 검증

| 항목 | 결과 |
| --- | --- |
| targets | 123 |
| reused_skipped | 11 |
| model | `BAAI/bge-m3` |
| dimension | 1024 (전 건) |
| input content_hash 보존 | True (sha256 재계산 일치) |
| chunk_id ↔ embedding 1:1 | True |
| duplicate embedding target | 0 |
| missing embedding | 0 |
| vector 정규화 | 전 건 L2 norm ≈ 1.0 (`normalize_embeddings=True`) |

## 산출물

- `data/outputs/evidence_coverage/embeddings/evidence_embeddings.jsonl` (123 rows,
  chunk_id/model/dimension/content_hash/vector 전체 — 용량이 커서 git에 커밋하지
  않는다. `data/`가 `.gitignore` 대상인 정책을 그대로 따른다)
- `data/outputs/evidence_coverage/evidence_embedding_manifest.csv` (123 rows,
  벡터 대신 `vector_sha256`/`vector_l2_norm`만 담은 경량 요약 — git에 커밋)

## 판정

`READY_FOR_DB_WRITE: NO` (별도 승인 대기)

임베딩 생성까지만 승인됐다. canonical `evidence_chunk`/`evidence_document`/
`evidence_chunk_ingredient` INSERT·REPLACE·REMOVE 실행은 명시적 지시가 있을 때
진행한다.
