# Evidence DB Load Plan Report

## 목적과 범위

combined evidence bundle(PubMed 93 + CIR new 5 + CIR reuse 11-link)을 canonical
v4 DB와 비교해 실제 embedding/DB write 전에 INSERT/REUSE/UPDATE_REQUIRED/CONFLICT
분류를 확정한다. 이 단계에서는 embedding, DB mutation, Agent/Backend 수정, main
merge를 전혀 하지 않았다 — 계획 산출물만 생성했다.

## 방법

- 기준 dump: `skincare_reference_2026-09-21_v4.dump`(alembic `9f4c2a7d8e61`)를 별도
  임시 DB(`evidence_load_plan_check`)에 읽기 전용으로 복원해 조회했고, 확인 후
  drop했다. canonical DB는 무변경.
- PubMed dedup key: **PMID 우선**. PMID가 일치하면 title/doi/url/content_hash를
  추가로 비교했다.
- CIR: canonical CIR document 10건과 신규 5건의 `source_id`(attachment id)를
  비교해 복제 여부를 확인했다. CIR reuse 11-link는 canonical chunk_id가 이미
  존재하는지, `(chunk_id, ingredient_id)` 조합이 이미 있는지 확인했다.

## 비교 결과

### Document

| action | 건수 | 설명 |
| --- | --- | --- |
| INSERT | 86 | PubMed 신규 81 + CIR 신규 5. canonical에 없음 |
| REUSE | 11 | PMID 일치, title/doi/url 완전 동일 |
| UPDATE_REQUIRED | 1 | PMID `16766489`. DOI/URL은 동일하지만 title 끝에 마침표 유무 차이(`...production.` vs `...production`) |
| CONFLICT | 0 | 없음. CIR 신규 5건은 canonical CIR 10건과 `source_id` 겹침 없음(복제 위험 없음) |
| DECISION_REQUIRED | 13 | canonical PubMed 25건 중 최종 QA bundle(93)에 없는 문서. 아래 "결정 필요" 참고 |

### Chunk

| action | 건수 | 설명 |
| --- | --- | --- |
| INSERT | 122 | PubMed 신규 81 + CIR 신규 41 |
| REUSE | 11 | canonical과 `content_hash` 완전 동일 |
| CONFLICT | 1 | PMID `16766489` chunk. 아래 "결정 필요" 참고 |

### Ingredient link

| action | 건수 | 설명 |
| --- | --- | --- |
| INSERT | 134 | PubMed 신규 84(81 document + 3건 복수 성분) + CIR 신규 39 + CIR reuse 11 |
| EXISTS | 12 | overlap 12개 PMID의 기존 link와 `(chunk_id, ingredient_id)` 완전 일치 |
| CONFLICT | 0 | 없음 |

## PubMed 겹침 상세

- **canonical 기존 25건 중 최종 bundle(93건)과 겹치는 PMID: 12건**
  (`12190621, 16029679, 16766489, 17515510, 18503551, 24509969, 26206496,
  30945430, 33811776, 37584240, 38299457, 40613435`)
- **canonical에만 있고 final bundle에는 없는 PubMed document: 13건**

  | PMID | ingredient(canonical) |
  | --- | --- |
  | 10971324 | Niacinamide |
  | 11702613 | Retinol |
  | 17613133 | Dipotassium Glycyrrhizate |
  | 21822427 | Niacinamide |
  | 21982351 | Panthenol |
  | 27324942 | Hyaluronic Acid |
  | 29947134 | Retinol |
  | 34348350 | Ceramide NP |
  | 38618759 | Niacinamide |
  | 38843906 | Tranexamic Acid |
  | 40177799 | Allantoin |
  | 40682399 | Ceramide NP |
  | 40826371 | Tranexamic Acid |

- **final bundle에는 있으나 canonical에 없는 PubMed document: 81건**(INSERT 대상,
  `evidence_db_load_plan_documents.csv`에 전부 나열)

## 결정 필요(임의 처리 금지)

### 1) PMID `16766489` — document title 차이 + chunk content 형식 충돌

- Document: canonical title이 `The effect of 2% niacinamide on facial sebum
  production`(마침표 없음), bundle title은 `...production.`(마침표 있음). DOI/URL은
  완전 동일해 같은 논문으로 확인된다.
- Chunk: canonical chunk(`parser_version=live-bge-m3-smoke-v1`)는 PubMed 인용
  헤더(저널·저자·기관 정보)와 `PMID:` 각주까지 포함한 **원문 그대로의 형식**이고,
  bundle chunk(`parser_version=pubmed-abstract-v1`)는 **abstract 본문만 남긴
  정제된 형식**이다. 같은 논문이지만 content_hash가 다르다.
- 어느 쪽 형식을 canonical `evidence_chunk.content`로 유지할지(정제된 QA 버전으로
  교체 vs 기존 smoke 버전 유지 vs 둘 다 보존) 결정이 필요하다. 이 chunk는
  Niacinamide ingredient link가 이미 존재해(`EXISTS`) link 자체는 영향받지 않지만,
  embedding 재생성 여부가 이 결정에 달려 있다.

### 2) 기존 PubMed 25건 중 최종 QA에서 탈락한 13건 처리 방침

- 13건 전부가 최종 QA bundle에서 빠졌다(위 표 참고). 이 중 어떤 성분들은
  대체 논문으로 커버되지만(Niacinamide, Retinol, Ceramide NP, Tranexamic Acid 각 2건),
  일부는 유일한 canonical 근거였을 수 있다(`Dipotassium Glycyrrhizate`,
  `Panthenol`, `Hyaluronic Acid`, `Allantoin` 각 1건뿐).
- 선택지: **삭제(evidence_document/chunk에서 제거) / 비활성(status 플래그로 검색
  제외, 데이터는 보존) / 유지(최종 bundle과 무관하게 그대로 둠)**. 임의로 고르지
  않는다.

### 3) PMID `30945430` — canonical에 있던 ingredient link 하나가 QA에서 빠짐

- canonical에는 이 document/chunk가 `Madecassoside`와 `Panthenol` **두 성분**에
  링크돼 있다. 최종 QA bundle은 이 논문을 `Madecassoside` 전용으로만 채택했다
  (제품이 panthenol+madecassoside+copper-zinc-manganese 복합 처방이라 단일 성분
  근거로 보기엔 `Panthenol` 쪽은 QA에서 제외된 것으로 보인다).
- document/chunk 자체는 REUSE 대상이라 이 시나리오는 `evidence_db_load_plan_links.csv`에는
  별도 행으로 나타나지 않는다(canonical에만 있는 link라 bundle 쪽에서 만들어지는
  파일이 아니기 때문). 이 canonical `Panthenol` link를 유지할지 제거할지 결정이
  필요하다 — 위 13건과 같은 성격의 질문이라 함께 결정해달라고 요청한다.

## 산출물

- `evidence_db_load_plan_documents.csv` (111 rows: bundle 98 + canonical-only 13)
- `evidence_db_load_plan_chunks.csv` (134 rows)
- `evidence_db_load_plan_links.csv` (146 rows)

## 판정

`READY_FOR_EMBEDDING: NO`

위 3가지 결정(16766489 chunk 형식, 탈락 13건 처리 방침, 30945430의 Panthenol
link 처리)이 확정되기 전에는 embedding/DB write를 진행하지 않는다.
