# Evidence DB Write Complete Report

## 실행

- 대상: canonical v4(`skincare_reference_2026-09-21_v4.dump`, alembic `9f4c2a7d8e61`)를
  복원한 로컬 임시 DB(`evidence_v5_write`)에 `FINAL_EVIDENCE_DB_ACTION_PLAN`을 그대로 반영.
- 코드: `data/scripts/evidence_db_writer.py`(`EvidenceBundleDbWriter`) +
  `data/scripts/evidence_db_writer_schemas.py`. 단일 `AsyncSession`으로 문서
  INSERT → 청크 INSERT/REPLACE → 링크 INSERT/REMOVE → 문서 REMOVE 순으로 처리하고
  **마지막에 딱 한 번 commit**했다. 도중 예외가 나면 `except`에서 `rollback()`하고
  그대로 재발생시킨다 - 실제로 1차 시도에서 CIR reuse link가 참조하는 기존 chunk PK를
  못 찾는 버그(`KeyError`)가 났고, 그 트랜잭션은 commit 전이라 DB가 그대로 v4
  baseline(46/8369/8377)으로 남아 있는 것을 확인한 뒤 코드를 고쳐 재실행했다.
- schema 변경, Agent/Backend 수정, 추가 수집/QA는 하지 않았다.

## Transaction

| | 건수 |
| --- | --- |
| Documents insert | 86 |
| Documents remove | 6 |
| Chunks insert | 122 |
| Chunks replace | 1 |
| Chunks remove(cascade) | 6 |
| Links insert | 134 |
| Links remove(cascade 6 + 단독 1) | 7 |

document REMOVE는 `evidence_chunk.document_id`/`evidence_chunk_ingredient.evidence_chunk_id`의
`ON DELETE CASCADE`로 그 document의 chunk 1건·link 1건이 자동 정리됐다(6건 각각).
PMID 30945430의 Panthenol link 1건만 별도 `DELETE`로 처리했다(같은 chunk의
Madecassoside link는 그대로 유지).

## Post-write counts

| table | 기대값 | 실제값 |
| --- | --- | --- |
| evidence_document | 126 | **126** |
| evidence_chunk | 8485 | **8485** |
| evidence_chunk_ingredient | 8504 | **8504** |

## Integrity

| 항목 | 결과 |
| --- | --- |
| embedding NULL | 0 |
| chunk orphan(document 없음) | 0 |
| link orphan(chunk 없음) | 0 |
| link orphan(ingredient 없음, FK) | 0 |
| duplicate `chunk_id` | 0 |
| duplicate `(source_type, source_id)` document | 0 |
| duplicate `(evidence_chunk_id, ingredient_id)` link | 0 |
| embedding dimension ≠ 1024 | 0 |
| provenance missing(`source_id`) | 0 |

## Special-case validation

| 대상 | 확인 내용 | 결과 |
| --- | --- | --- |
| PMID 16766489 | document identity 유지(동일 document, 새 row 아님), `parser_version`이 `pubmed-abstract-v1`(최종 QA)로 교체, title이 `...production.`(QA 값)로 갱신, `embedding_model=BAAI/bge-m3`로 재계산된 임베딩 반영 | PASS |
| PMID 30945430 | `evidence_chunk_ingredient`에 `Madecassoside`만 남고 `Panthenol`은 없음 | PASS |
| human EXCLUDE 6건(17613133/27324942/34348350/38843906/40177799/40826371) | `evidence_document`에서 전부 조회되지 않음(0 rows) | PASS |
| human KEEP 4건(10971324/21822427/21982351/40682399) | `evidence_document`에 전부 존재 | PASS |
| DEFER 3건(11702613/29947134/38618759) | document/chunk가 그대로 존재하고 `content_hash`가 write 이전과 동일(코드상 이 3건은 어떤 INSERT/UPDATE/DELETE 대상 목록에도 없어 손댈 방법이 없었음) | PASS |

## Canonical dump

- 파일: `data/skincare_reference_2026-09-22_v5.dump`(로컬 경로, git에는 커밋하지 않음 -
  v4와 같은 정책. 팀 공유는 기존처럼 Google Drive로 별도 업로드가 필요하다)
- 크기: 80,744,958 bytes
- SHA-256: `48d8ef1411d6a2f066b4b554aed2003ef379723934daffe07cc1770e1755b3e5`
  (체크섬 파일: `data/skincare_reference_2026-09-22_v5.dump.sha256`)
- **v4 원본(`/Downloads/.../skincare_reference_2026-09-21_v4.dump`)은 전혀 덮어쓰지
  않았다** - 크기(80,015,861 bytes)와 SHA-256(`8c3eb724f8...`) 모두 write 전후 동일함을 재확인했다.
- v5 dump 자체를 별도의 빈 DB(`v5_restore_verify`)에 복원해 `evidence_document=126`/
  `evidence_chunk=8485`/`evidence_chunk_ingredient=8504`/`embedding NULL=0`과 다른
  테이블(`product=2262`, `ingredient_master=21974`, v4와 동일)이 멀쩡한 것까지
  확인한 뒤 그 검증용 DB는 drop했다.

## 남은 일(이번 범위 밖, 참고용)

- v5 dump를 팀 Google Drive에 올리고 `docs/data/DB_REFERENCE_HANDOFF.md`를 v5
  기준으로 갱신하는 것은 이번 작업 범위에 없어 하지 않았다. 필요하면 별도로
  요청해 달라.

## 판정

`READY_FOR_RETRIEVER_EVAL: YES`

계획했던 모든 action이 오차 없이 반영됐고, post-write integrity와 special-case
검증이 전부 통과했다. 새 canonical dump(v5)도 별도 복원으로 재검증했다.
