# Combined Evidence Bundle Report

## 입력

- PubMed final KEEP bundle(`pubmed_final_bundle.jsonl`): 93 unique PMID / 96 ingredient-paper 연결(3개
  문서가 성분 2개씩과 연결).
- CIR new(`cir_final_documents.jsonl` / `cir_final_chunks.jsonl` / `cir_chunk_ingredient_links.csv`):
  document 5 / chunk 41 / link 39 (전부 `NEW_DOCUMENT`).
- CIR existing reuse links([CIR_FINAL_BUNDLE_REPORT.md](CIR_FINAL_BUNDLE_REPORT.md)에서 확정한 11건,
  `EXISTING_DOCUMENT_REUSE`): canonical dump(`skincare_reference_2026-09-21_v4.dump`)에 이미 적재된
  CIR document 10건 / chunk 56건 중, 실제 chunk 본문에 exact ingredient name이 있는 경우만 link.

## 정책

- embedding, DB write는 수행하지 않았다. 읽기 전용 확인을 위해 canonical dump를 임시 로컬 DB에
  복원해 조회했고, 확인 직후 그 임시 DB만 drop했다(`docs/data/DB_REFERENCE_HANDOFF.md` 3절 절차).
- CIR reuse 11건은 **document/chunk를 복제하지 않고 link 행만** 추가했다. 해당 chunk 본문은 이미
  canonical DB의 CIR document 안에 있으므로, 이 bundle의 `combined_evidence_documents.jsonl`/
  `combined_evidence_chunks.jsonl`에는 그 5개 canonical CIR reuse document(Hyaluronates, Ceramides,
  Tocopherols and Tocotrienols — 정확히는 이 중 3개 문서가 8개 성분에 걸쳐 재사용됨)를 다시 넣지
  않았다. `combined_evidence_chunk_ingredient_links.csv`의 `document_source_id`/`chunk_id`로
  canonical DB 쪽 document/chunk를 그대로 참조한다.

## 산출

| 파일 | 행 수 |
| --- | --- |
| `combined_evidence_documents.jsonl` | 98 (PubMed 93 + CIR new 5) |
| `combined_evidence_chunks.jsonl` | 134 (PubMed 93 + CIR new 41) |
| `combined_evidence_chunk_ingredient_links.csv` | 146 (PubMed NEW_DOCUMENT 96 + CIR NEW_DOCUMENT 39 + CIR EXISTING_DOCUMENT_REUSE 11) |

## 검증

- Duplicate document(`source_id` 기준): 0
- Duplicate chunk(`chunk_id` 기준): 0
- Duplicate link(`chunk_id` + `ingredient_id` 조합 기준): 0
- Unresolved ingredient_id(빈 값 또는 이름 조회 실패): 0
- Missing provenance(`source_id`/`url` 누락 document): 0
- PubMed unique documents: 93 (입력과 동일하게 유지)
- CIR new documents: 5 (입력과 동일하게 유지)
- CIR reuse: link 11건만 추가, document/chunk 복제 0건
- embedding 필드: 산출물에 없음(생성하지 않음)
- DB write: 0건(운영 DB 무변경, 임시 검증 DB는 조회 후 drop)

## 판정

`COMBINED_EVIDENCE_BUNDLE_COMPLETE: YES`
