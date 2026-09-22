# CIR Final Bundle Report

## 입력 및 정책

- 공식 CIR PDF 5건을 사용했고 웹 검색·embedding·DB write는 수행하지 않았다.
- Retinol 2017은 `re_review_summary`이며 full safety assessment로 취급하지 않았다.
- Ascorbic Acid와 Sodium Ascorbyl Phosphate는 document 1건을 공유하고 chunk linkage만 분리했다.
- Salicylic Acid는 2025 amended report, Capryloyl Salicylic Acid는 2024 standalone reassessment만 사용했다.
- chunk는 물리 page와 section을 보존하며 REFERENCES 이후와 back matter를 제외했다.

## 읽기 전용 snapshot

- `/private/tmp/skincare_ingredient_master.sql`
- `/private/tmp/skincare_evidence_document.sql`
- `/private/tmp/skincare_evidence_chunk.sql`
- `/private/tmp/skincare_evidence_chunk_ingredient.sql`

- snapshot CIR document 수: 0
- 기존 8개 재사용 blocker: 최신 사용 가능 SQL snapshot에 CIR document/chunk가 없어 기존 8개 재사용 후보를 검증할 수 없음

## 산출 및 검증

- Documents: 5
- Chunks: 41
- Ingredient links: 39 (NEW_DOCUMENT 39, EXISTING_DOCUMENT_REUSE 0)
- Scope verification: 6/6 verified
- Unresolved ingredient_id: 0
- Duplicate document/chunk/link: 0
- Missing provenance: 0
- Page-crossing: 0
- REFERENCES 이후 chunk: 0
- scope_verified=false link: 0

## 판정

`READY_FOR_COMBINED_EVIDENCE_BUNDLE: NO`

신규 5-document bundle은 완성됐다. 기존 CIR 8개 재사용 링크는 snapshot에서 실제 CIR
document/chunk를 확인할 수 있을 때만 생성해야 하며, 현재 blocker가 있으면 임의 생성하지 않는다.
