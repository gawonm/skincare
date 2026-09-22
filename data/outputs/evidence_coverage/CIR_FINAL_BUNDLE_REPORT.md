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
- 기존 8개 재사용 blocker(당시): 최신 사용 가능 SQL snapshot에 CIR document/chunk가 없어 기존 8개 재사용 후보를 검증할 수 없음

## CIR reuse linkage (canonical dump 기준, 갱신)

- 기준 dump: `skincare_reference_2026-09-21_v4.dump` (SHA-256 `8c3eb724f86f706614dbf2c37d6fb156591e9dbb85166cee423ac213abe30111`, alembic `9f4c2a7d8e61`).
  읽기 전용 확인 목적으로 빈 임시 DB(`cir_reuse_check`)에 복원해 조회했고, 확인 후 해당 임시 DB만 drop했다. 기존 canonical DB는 쓰지 않았고 DB write는 0건이다.
- canonical dump에는 CIR document 10건 / CIR chunk 56건이 이미 적재돼 있다(MFDS 11 + CIR 10 + PubMed 25 documents, MFDS 8,288 + CIR 56 + PubMed 25 chunks).
- 대상 8개 성분 중 7개는 `ingredient_master`에서 `ingredient_id`를 확인했고, 실제 CIR chunk 본문에서 exact name(또는 old_names_en의 승인된 equivalent)이 그대로 등장하는 chunk만 링크했다. title/family 기준 상속은 전혀 쓰지 않았다.

| 성분 | 재사용 CIR document | 근거 chunk | 결과 |
| --- | --- | --- | --- |
| Hydrolyzed Hyaluronic Acid | Safety Assessment of Hyaluronates as Used in Cosmetics | `:12:DISCUSSION:3`, `:13:CONCLUSION:6` | 링크 2건 |
| Sodium Acetylated Hyaluronate | 〃 | `:12:DISCUSSION:3`, `:13:CONCLUSION:6` | 링크 2건 |
| Hydrolyzed Sodium Hyaluronate | 〃 | `:12:DISCUSSION:3` | 링크 1건 |
| Potassium Hyaluronate | 〃 | `:12:DISCUSSION:3`, `:13:CONCLUSION:6` | 링크 2건 |
| Ceramide AP | Safety Assessment of Ceramides as Used in Cosmetics | `:8:Conclusion:2` | 링크 1건 |
| Ceramide EOP | 〃 | `:8:Conclusion:2` | 링크 1건 |
| Tocopheryl Acetate | Safety Assessment of Tocopherols and Tocotrienols as Used in Cosmetics | `:31:Discussion:0`, `:31:Discussion:1` | 링크 2건 |
| Phytosphingosine | (없음) | — | **링크 없음** |

**Phytosphingosine은 링크하지 않았다.** Ceramides 보고서 Conclusion chunk(`:8:Conclusion:2`)에
"Phytosphingosine" 문자열이 나타나지만, 실제로는 전부 `Caprooyl Phytosphingosine` /
`Hydroxylauroyl Phytosphingosine*` / `Hydroxycapryloyl Phytosphingosine*` /
`Hydroxycaproyl Phytosphingosine*` 같은 **다른 유도체 화합물명의 일부**이며, "Phytosphingosine"
단독 표기는 어떤 CIR chunk에도 없다. substring match만으로 링크하면 false scope link가 되므로
제외했다(규칙: scope_verified=false link 금지).

같은 이유로 Tocopherols 보고서 Conclusion chunk(`:31:Conclusion:2`)의 `Ascorbyl tocopheryl
acetate*`도 "Tocopheryl Acetate" 단독 표기가 아니라 다른 화합물이라 링크에서 제외했다.
Tocopheryl Acetate는 같은 문서의 Discussion chunk 2건(`:31:Discussion:0`, `:31:Discussion:1`)에
"tocopheryl acetate"가 독립적으로 등장하는 것을 확인해 그 2건만 링크했다.

## 산출 및 검증

- Documents: 5 (신규) + CIR reuse는 기존 canonical document 재사용이라 document 신규 생성 없음
- Chunks: 41 (신규)
- Ingredient links: 50 (NEW_DOCUMENT 39, EXISTING_DOCUMENT_REUSE 11)
- Scope verification(신규 5-document): 6/6 verified
- Scope verification(CIR reuse 8개 대상): 7/8 verified, 1건(Phytosphingosine) 유효 링크 없음(정상 판정, 오류 아님)
- Unresolved ingredient_id: 0
- Duplicate document/chunk/link: 0 ((chunk_id, ingredient_id) 조합 기준 확인)
- Missing provenance: 0
- Page-crossing: 0
- REFERENCES 이후 chunk: 0
- scope_verified=false link: 0
- DB mutation: 0 (읽기 전용 조회, 임시 검증용 DB만 생성 후 drop)

## 판정

`CIR_REUSE_LINKAGE_FINAL`

- Canonical snapshot: `skincare_reference_2026-09-21_v4.dump` (alembic `9f4c2a7d8e61`)
- CIR documents found: 10
- CIR chunks found: 56
- Reuse links created: 11
- Ingredients with no valid reuse link: 1 (Phytosphingosine)
- Scope verification: 7/8 (Phytosphingosine 제외 전원 verified)
- Duplicates: 0
- Tests: unresolved ingredient_id 0 / duplicate link 0 / false scope link 0 / 기존 NEW_DOCUMENT 39건 유지 / DB mutation 0
- `CIR_FINAL_COMPLETE: YES`

신규 5-document bundle과 CIR 8개 재사용 링크(7건 확정, Phytosphingosine 1건 근거 없음 확정)가 모두
끝나 `READY_FOR_COMBINED_EVIDENCE_BUNDLE: YES`. 다음 단계로 PubMed + CIR combined evidence bundle을
진행한다.
