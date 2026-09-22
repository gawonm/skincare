# Legacy PubMed Re-Review Sheet Report

## 범위

`evidence_db_load_plan_pubmed_13_lineage.csv`에서 `recommendation=RE_REVIEW`인
10건에 대해 사람이 KEEP/EXCLUDE/UNCERTAIN을 판단할 수 있는 review sheet를
만들었다. `DEFER` 3건(11702613, 29947134, 38618759)은 `over_budget`(성분당 후보
상한 초과로 잘린 것뿐, 품질 문제 아님)이라 이번 재검토 대상에서 제외하고 기존
상태를 그대로 보존했다 — 이 3건은 review sheet에 없다.

## 대상 10건

10971324, 17613133, 21822427, 21982351, 27324942, 34348350, 38843906,
40177799, 40682399, 40826371

## 산출물

`data/outputs/evidence_coverage/legacy_pubmed_re_review_sheet.csv` (10 rows)

컬럼: `pmid`, `linked_ingredient`, `title`, `full_abstract`,
`existing_db_chunk_content`, `existing_db_chunk_id`, `collection_lineage`,
`auto_exclusion_reason`, `route`, `study_type`, `directness`, `skin_relevance`,
`claim_topic`, `existing_ingredient_linkage`, `reviewer_verdict_so_far`,
`proposed_verdict`(빈 칸).

- `full_abstract`: `pubmed_full.jsonl`의 abstract 원문(전수 수집 단계 기록).
- `existing_db_chunk_content`: canonical `evidence_chunk.content` 원문(실제 DB에
  적재된 텍스트) — 두 원문을 함께 제공해 자동 탈락 사유만으로 판단하지 않고
  논문 본문 자체를 보고 판단할 수 있게 했다.
- `directness`: 전수 수집 단계의 `evidence_grade`(예: `direct_single_topical_human`,
  `topical_review`, `not_graded`)를 그대로 옮겼다.
- `proposed_verdict`: 전부 빈 칸으로 비워 뒀다(KEEP/EXCLUDE/UNCERTAIN 중 선택은
  사람 몫).

## PMID 21822427 특이사항

`pubmed_full.jsonl`/`pubmed_smoke50.jsonl` 전수 수집 파이프라인 어디에도 이
PMID 기록이 없다. `full_abstract`는 빈 값이지만, canonical DB의
`existing_db_chunk_content`(1,905자)는 그대로 제공했으므로 원문 자체는 확인할
수 있다. `route`/`study_type`/`directness`/`skin_relevance`/`claim_topic`은
파이프라인 기록이 없어 `N/A`로 표시했고, `collection_lineage`와
`auto_exclusion_reason`에도 "출처 불명"이라고 명시했다 — 값을 임의로 추정해
채우지 않았다.

## 완결성 검증

- 요청한 10개 PMID 전부 포함: True
- `existing_db_chunk_content` 누락 0건(10건 전부 원문 확보)
- `title` 누락 0건
- `proposed_verdict` 사전 기입 0건(전부 빈 칸으로 사람 판단 대기)

## 판정

`LEGACY_PUBMED_REVIEW_READY: YES`

10건 전체가 사람이 KEEP/EXCLUDE/UNCERTAIN을 판단하기에 충분한 원문·lineage를
갖췄다. DB mutation은 하지 않았고, 판정이 나오면 그 결과만
`evidence_db_load_plan_documents.csv`/`evidence_db_load_plan_pubmed_13_lineage.csv`에
반영하면 된다.
