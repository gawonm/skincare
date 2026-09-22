# Evidence DB Load Plan Report

## 목적과 범위

combined evidence bundle(PubMed 93 + CIR new 5 + CIR reuse 11-link)을 canonical
v4 DB와 비교해 실제 embedding/DB write 전에 INSERT/REUSE/UPDATE_REQUIRED/CONFLICT
분류를 확정하고, 3가지 결정 사항을 반영했다. 이 단계에서도 embedding 실제 실행,
DB mutation, Agent/Backend 수정, main merge는 전혀 하지 않았다 — 계획 산출물만
갱신했다.

## 방법

- 기준 dump: `skincare_reference_2026-09-21_v4.dump`(alembic `9f4c2a7d8e61`)를 별도
  임시 DB에 읽기 전용으로 복원해 조회했고, 확인 후 drop했다. canonical DB는 무변경.
- PubMed dedup key: **PMID 우선**. PMID가 일치하면 title/doi/url/content_hash를
  추가로 비교했다.
- 13건 lineage는 `pubmed_full.jsonl`(전수 수집, `disposition`/`in_final_result`/
  `reason` 보유)과 `pubmed_final_selected_qa_reviewed.csv`(`reviewer_verdict`/
  `reviewer_reason` 보유)를 PMID 기준으로 조회해 재구성했다.

## 결정 반영 결과

### Decision 1 — PMID `16766489`

- **Document**: `KEEP_IDENTITY`. 동일 PMID/DOI/URL이라 새 EvidenceDocument를 만들지
  않고 기존 document identity(같은 id)를 유지한다. title 필드는 추후 DB write 시
  최종 QA bundle 값(`...production.`)으로 갱신 예정.
- **Chunk**: `REPLACE`. canonical legacy chunk(`parser_version=live-bge-m3-smoke-v1`,
  PubMed 인용 헤더·저자·각주 포함 원문 형식)를 최종 QA content(`parser_version=
  pubmed-abstract-v1`, abstract 본문만)로 교체하기로 확정.
- **Embedding**: `RECOMPUTE`로 표시(`evidence_db_load_plan_chunks.csv`의
  `embedding_action` 컬럼). 실제 BGE-M3 재계산은 이번 단계에서 실행하지 않았다.
- 이 chunk의 Niacinamide ingredient link는 이미 canonical에 있고(`EXISTS`) 이번
  결정과 무관하게 그대로 유지된다.

### Decision 2 — 기존 PubMed 25건 중 final bundle에 없는 13건

`REMOVE`로 바로 확정하지 않고, 13건 전체 exclusion lineage를 재구성했다
(`evidence_db_load_plan_pubmed_13_lineage.csv`). 결과:

| recommendation | 건수 | 의미 |
| --- | --- | --- |
| REMOVE | 0 | 명시적 QA `EXCLUDE` 판정을 받은 건 없음 |
| RE_REVIEW | 10 | 사람 재검토가 필요(아래 설명) |
| DEFER | 3 | 시스템 용량(per-ingredient cap) 때문에 잘린 것뿐, 급하지 않음 |
| NOT_REVIEWED(reviewer_verdict) | 11 | 사람 QA 단계까지 간 적이 없음(자동 선별 단계에서 멈춤) |
| UNCERTAIN(reviewer_verdict) | 2 | 사람이 검토했지만 KEEP/EXCLUDE를 확정하지 못함 |

**DEFER (3건, `over_budget`만 해당)** — 전수 수집 단계에서 성분당 후보 상한(10건)
때문에 순위에서 밀린 것뿐, 품질 문제로 배제된 게 아니다. 해당 성분들은 최종
bundle에 이미 충분한 대체 논문이 있다.

| PMID | ingredient | 최종 bundle 내 해당 성분 논문 수 |
| --- | --- | --- |
| 11702613 | Retinol | 3 |
| 29947134 | Retinol | 3 |
| 38618759 | Niacinamide | 3 |

**RE_REVIEW (10건)** — 자동 선별 사유(`non_clinical_study_design`,
`route_unclear`, `comparator_only`)나 사람의 `UNCERTAIN` 판정 자체가 evidentiary
validity에 직접 관련된 항목이라, 대체 논문 존재 여부와 무관하게 사람이 최종
KEEP/EXCLUDE를 정해야 한다.

| PMID | ingredient | 사유 | 비고 |
| --- | --- | --- | --- |
| 10971324 | Niacinamide | `non_clinical_study_design`(Cholesterol/Sphingolipids 질의로 수집) | title이 사실상 Niacinamide 논문("Nicotinamide increases biosynthesis of ceramides...")으로 보이나, Niacinamide 기준으로는 한 번도 QA 검토된 적이 없음 |
| 17613133 | Dipotassium Glycyrrhizate | `route_unclear` | title이 CIR 공식 safety assessment 보고서 제목과 동일 — 1차 연구 논문이 아닐 수 있음. 최종 bundle에 이 성분의 PubMed 근거가 0건이라 이 판정이 중요함 |
| 21822427 | Niacinamide | 출처 불명 | `pubmed_full.jsonl`/`pubmed_smoke50.jsonl` 어디에도 없음. canonical에 왜/어떻게 적재됐는지 pipeline 기록으로 추적 불가 |
| 21982351 | Panthenol | `route_unclear` | Decision 3(아래)로 Panthenol이 link 1건을 이미 잃은 상태라 함께 고려 필요 |
| 27324942 | Hyaluronic Acid | 사람 `UNCERTAIN`("다양한 의학적 HA 적용 포괄 systematic review라 topical skincare 근거만 분리됐는지 불명확") | 최종 bundle에 이 성분의 PubMed 근거가 1건뿐 |
| 34348350 | Ceramide NP | `non_clinical_study_design` | 최종 bundle에 Ceramide NP 논문 2건(다른 PMID) 있음 |
| 38843906 | Tranexamic Acid | `route_unclear` | 최종 bundle에 Tranexamic Acid 논문 3건 있음 |
| 40177799 | Allantoin | 사람 `UNCERTAIN`(복합 처방이라 Allantoin 단독 효과 분리 어려움) | 최종 bundle에 이 성분의 PubMed 근거가 2건 있음 |
| 40682399 | Ceramide NP | `non_clinical_study_design` | 최종 bundle에 Ceramide NP 논문 2건(다른 PMID) 있음 |
| 40826371 | Tranexamic Acid | `comparator_only`(비교대조군으로만 언급) | 최종 bundle에 Tranexamic Acid 논문 3건 있음 |

- 규칙대로 `NOT_REVIEWED` 11건은 자동 삭제하지 않았고, `REMOVE`로 분류한 건 0건이다.
- 이 13건에 대한 **삭제/비활성/유지 최종 판단은 아직 열려 있다.** 위 lineage를
  검토한 뒤 다시 결정해달라고 요청한다. 이 결정이 남아 있어도 신규 86건
  document/122건 chunk/134건 link의 INSERT 진행에는 영향이 없다(서로 다른 PMID라
  독립적임).

### Decision 3 — PMID `30945430`

- canonical에 이 document/chunk가 `Madecassoside`와 `Panthenol` 두 성분에 링크돼
  있었는데, 최종 QA는 `Madecassoside` linkage만 유지하고 `Panthenol` linkage는
  제거하기로 확정했다(복합 처방에 Panthenol이 포함됐다는 이유만으로 단독 evidence로
  유지하지 않음).
- `evidence_db_load_plan_links.csv`에 `action=REMOVE`, `linkage_type=CANONICAL_ONLY`
  행을 추가했다(`in_combined_bundle=False`로 표시 — bundle에서 온 행이 아니라
  canonical에만 있던 link라는 뜻). `Madecassoside` link는 그대로 `REUSE`
  대상(combined bundle에 이미 포함)으로 유지된다.
- 실제 삭제(DB mutation)는 이번 단계에서 실행하지 않았다.

## 비교 결과 (갱신)

### Document (111 rows)

| action | 건수 | 설명 |
| --- | --- | --- |
| INSERT | 86 | PubMed 신규 81 + CIR 신규 5 |
| REUSE | 11 | PMID 일치, title/doi/url 완전 동일 |
| KEEP_IDENTITY | 1 | PMID `16766489`, Decision 1 |
| RE_REVIEW | 10 | Decision 2, 사람 재검토 필요 |
| DEFER | 3 | Decision 2, 용량 사유로 급하지 않음 |

### Chunk (134 rows)

| action | 건수 | 설명 |
| --- | --- | --- |
| INSERT | 122 | PubMed 신규 81 + CIR 신규 41 |
| REUSE | 11 | canonical과 content_hash 완전 동일 |
| REPLACE | 1 | PMID `16766489`, Decision 1 |

### Ingredient link (147 rows: bundle 146 + canonical-only 1)

| action | 건수 | 설명 |
| --- | --- | --- |
| INSERT | 134 | PubMed 신규 84 + CIR 신규 39 + CIR reuse 11 |
| EXISTS | 12 | overlap 12개 PMID의 기존 link와 동일 |
| REMOVE | 1 | PMID `30945430`의 Panthenol link, Decision 3 |

## 산출물

- `evidence_db_load_plan_documents.csv` (111 rows)
- `evidence_db_load_plan_chunks.csv` (134 rows, `embedding_action` 컬럼 추가)
- `evidence_db_load_plan_links.csv` (147 rows, `in_combined_bundle` 컬럼 추가)
- `evidence_db_load_plan_pubmed_13_lineage.csv` (13 rows, Decision 2 상세 lineage)

## 판정

`READY_FOR_EMBEDDING: YES`

3가지 결정이 모두 반영됐고 CONFLICT는 0건이다. INSERT 대상 86 document/122
chunk/134 link는 13건 재검토 결과와 무관하게 독립적으로 진행 가능하다. 단,
**실제 embedding 실행과 DB mutation은 별도의 명시적 지시가 있을 때 진행한다**
(이번 단계는 계획 확정까지만). 13건 중 RE_REVIEW 10건의 최종 KEEP/EXCLUDE
판단은 여전히 열려 있으며, 그 판단이 나오는 대로 해당 행만 load plan에 반영하면 된다.
