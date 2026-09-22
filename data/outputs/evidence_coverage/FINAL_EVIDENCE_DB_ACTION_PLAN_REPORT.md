# Final Evidence DB Action Plan Report

## 반영한 human verdict (10건)

| PMID | ingredient | verdict | 최종 action |
| --- | --- | --- | --- |
| 10971324 | Niacinamide | KEEP | document/chunk/link REUSE(canonical 유지) |
| 21822427 | Niacinamide | KEEP | document/chunk/link REUSE(canonical 유지) |
| 21982351 | Panthenol | KEEP | document/chunk/link REUSE(canonical 유지) |
| 40682399 | Ceramide NP | **KEEP**(초안 EXCLUDE에서 변경) | document/chunk/link REUSE, **combination/formulation evidence 전용 조건부** |
| 17613133 | Dipotassium Glycyrrhizate | EXCLUDE | document/chunk/link REMOVE |
| 27324942 | Hyaluronic Acid | EXCLUDE | document/chunk/link REMOVE |
| 34348350 | Ceramide NP | EXCLUDE | document/chunk/link REMOVE |
| 38843906 | Tranexamic Acid | EXCLUDE | document/chunk/link REMOVE |
| 40177799 | Allantoin | EXCLUDE | document/chunk/link REMOVE |
| 40826371 | Tranexamic Acid | EXCLUDE | document/chunk/link REMOVE |

**PMID 40682399 조건**: `directness = combination/formulation evidence`로만 취급한다.
Ceramide NP 단독 효능 근거로 사용을 금지하고, "Ceramide NP가 포함된 복합 크림에서
민감성 피부 장벽/증상 개선이 관찰됨" 수준으로만 인용한다. 이 조건은
`evidence_db_load_plan_documents.csv`/`_chunks.csv`/`_links.csv`의 `note` 컬럼에
명시했다 — 실제 DB에 반영할 때 `evidence_document.formulation_type=
combination_formulation`/`study_type` 등 기존 스키마 컬럼으로 옮겨야 한다(컬럼
자체는 이미 있음, 값 채우기만 남음).

DEFER 3건(11702613, 29947134, 38618759)은 그대로 canonical 상태를 보존했다
(action=`DEFER`, 이번 재검토·삭제 대상이 아님).

기존 결정도 그대로 유지했다: PMID 16766489(document `KEEP_IDENTITY` + chunk
`REPLACE` + embedding `RECOMPUTE`), PMID 30945430(Madecassoside link `REUSE`,
Panthenol link만 `REMOVE`).

## ⚠️ 작업 중 발견한 문제 — `legacy_pubmed_re_review_sheet.csv` 파일 손상 및 잠금

verdict를 반영하려고 이 파일을 다시 읽었더니 UTF-8 디코딩 에러가 났다. 원인을
확인해 보니:

- 현재 작업 디렉터리의 `legacy_pubmed_re_review_sheet.csv`가 **Excel/OneDrive로
  추정되는 다른 프로그램에 열려 있어 잠겨 있다**(`cp`/`mv`/`git checkout` 전부
  "Device or resource busy"로 실패했다). 아마 이 시트를 검토하려고 열어 두신
  것으로 보인다.
- 그 사이 한글 텍스트 일부가 깨졌다(`?`와 잘못된 바이트로 치환됨) — Excel이
  CSV를 다시 저장할 때 UTF-8이 아닌 인코딩(예: 시스템 기본 코드페이지)으로 쓰면
  흔히 생기는 문제다. git에 커밋된 버전(직전 커밋)은 정상 UTF-8이라 **git
  히스토리 쪽 데이터 손실은 없다.**
- 파일이 잠겨 있어 직접 덮어쓰지 않았다(열어서 보고 계실 수 있는 내용을 임의로
  바꾸지 않기 위함). 대신 **verdict가 채워진 최종본을
  `legacy_pubmed_re_review_sheet_final.csv`라는 새 파일로 만들었다** — 기존
  파일을 건드리지 않는다.

**확인 요청**: Excel에서 이 파일을 열어 두셨다면, 저장하지 말고 닫아 주세요
(현재 화면에 깨진 한글이 보인다면 저장하지 않은 상태일 가능성이 높다). 닫으신
뒤 `legacy_pubmed_re_review_sheet.csv`가 여전히 필요하면 알려주시면
`legacy_pubmed_re_review_sheet_final.csv`로 교체하겠다.

## 최종 집계

### Documents (111 rows)

| action | 건수 |
| --- | --- |
| INSERT | 86 |
| REUSE | 15 (bundle overlap 11 + human KEEP 4) |
| REPLACE/UPDATE | 1 (PMID 16766489) |
| REMOVE | 6 (human EXCLUDE) |
| DEFER | 3 (over_budget, 미검토 보존) |

### Chunks (147 rows)

| action | 건수 |
| --- | --- |
| INSERT | 122 |
| REUSE | 15 (bundle overlap 11 + human KEEP 4) |
| REPLACE | 1 (PMID 16766489) |
| REMOVE | 6 (human EXCLUDE) |

(DEFER 3건의 canonical chunk는 그대로 있으나 이번 action 대상이 아니라
`evidence_db_load_plan_chunks.csv`에 참고용으로만 `action=DEFER`로 남겨 뒀다 -
위 집계에는 포함하지 않음, `Documents:DEFER`와 동일한 3건이다.)

### Links (157 rows)

| action | 건수 |
| --- | --- |
| INSERT | 134 |
| EXISTS/REUSE | 16 (bundle overlap EXISTS 12 + human KEEP REUSE 4) |
| REMOVE | 7 (human EXCLUDE 6 + PMID 30945430의 Panthenol link 1) |

### Embeddings

| 상태 | 건수 |
| --- | --- |
| generated | 123 (INSERT 122 + REPLACE 1, `evidence_embedding_manifest.csv`에서 확인) |
| reused | 15 (bundle overlap 11 + human KEEP 4 — canonical `evidence_chunk.embedding` 그대로 사용, 재계산 없음) |
| missing | 0 |

## Validation

| 항목 | 결과 |
| --- | --- |
| unresolved ingredient_id/name | 0 |
| duplicate document(`source_id`) | 0 |
| duplicate chunk(`chunk_id`) | 0 |
| duplicate link(`chunk_id`+`ingredient_id`) | 0 |
| FK risk | 0 — `evidence_chunk.document_id`/`evidence_chunk_ingredient.evidence_chunk_id` 모두 `ON DELETE CASCADE`라 document REMOVE 시 자식 chunk/link가 자동 정리된다. PMID당 document:chunk:link가 1:1:1(30945430만 예외, link 2개 중 1개만 REMOVE)이라 다른 행이 고아가 되는 경우가 없다 |
| provenance missing | 0 |
| REMOVE 정합성 | document REMOVE 6건 = chunk REMOVE 6건, 그 chunk_id들이 link REMOVE와 정확히 일치(30945430만 링크 단독 REMOVE로 별도 확인됨) |
| REUSE 정합성 | human KEEP 4건의 chunk REUSE와 link REUSE가 정확히 일치 |

## 다음 단계 확인 (요청하신 3가지)

1. **verdict를 DB action manifest에 반영** — 완료
   (`evidence_db_load_plan_documents.csv` / `_chunks.csv` / `_links.csv`,
   `evidence_db_load_plan_pubmed_13_lineage.csv`에 `human_final_verdict`/
   `final_action`/`final_note` 컬럼 추가).
2. **최종 INSERT/REUSE/REPLACE/REMOVE 수 재계산** — 완료(위 표).
3. **123 embeddings와 load manifest 정합성 확인** — 완료.
   `evidence_embedding_manifest.csv`(123 rows)의 `chunk_id` 집합이
   `evidence_db_load_plan_chunks.csv`의 `action ∈ {INSERT, REPLACE}` 집합과
   정확히 일치한다(둘 다 122+1=123, 교집합 123, 차집합 0).
4. **DB write 직전 dry-run** — 아직 실행하지 않았다. dry-run 스크립트가 아직
   없으므로, 다음 지시에서 실행 방식(예: 기존 `mfds_evidence_embedding_run.py`
   패턴처럼 `--execute` 플래그가 없으면 자동으로 dry-run)을 어떻게 원하는지
   확인이 필요하다 — 이 리포트 하나로는 임의로 실행 스크립트를 만들지 않았다.

## 판정

`READY_FOR_DB_WRITE: NO`

계획(document/chunk/link 분류, embedding 생성, 정합성 검증)은 전부 끝났지만,
아래 두 가지가 남아 있어 실제 DB write는 아직 진행하지 않는다.

1. 위 파일 잠금/손상 이슈 확인(Excel에서 열려 있는 `legacy_pubmed_re_review_sheet.csv`
   처리 방침).
2. dry-run 스크립트 실행 및 결과 확인 — 요청하신 "DB write 직전 dry-run"은
   아직 만들지도 실행하지도 않았다. 다음 지시를 기다린다.

canonical DB write, embedding 실제 반영(INSERT/REPLACE/REMOVE 실행),
Agent/Backend 수정은 여전히 하지 않았다.
