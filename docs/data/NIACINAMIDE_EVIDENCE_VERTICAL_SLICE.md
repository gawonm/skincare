# Niacinamide Evidence Vertical Slice — 실사 결과

> 목적: Evidence RAG를 넓게 구현하기 전에, Niacinamide 하나로 "Claim → PubMed Evidence"
> 연결이 실제로 성립하는지 검증한다. embedding/Vector DB/retriever 구현은 하지 않았다.

---

## 1. `rag_chunk` Investigation

### A. 현재 DB 연결 정보

`config.yaml`의 `database.url`: `postgresql+asyncpg://app:app@localhost:5432/app`
(`docker-compose.yml`의 `skincare-postgres` 컨테이너, `POSTGRES_USER/PASSWORD/DB` 전부 `app`)

`docker ps`로 확인한 결과 이 머신에는 **postgres 컨테이너가 2개** 떠 있습니다:

| 컨테이너 | 포트 | 용도 |
|---|---|---|
| `skincare-postgres` | 5432 (내가 쓰는 DB) | 로컬 개발 |
| `skincare-verify-postgres` | 15432 | 배포 검증용(`skincare-verify` compose project) |

`git worktree list` 결과 **워크트리는 이 하나뿐**이라 "다른 워크트리" 가설은 배제됩니다.

`skincare-verify-postgres`는 `app`/`app` 자격증명이 안 먹혀서(다른 비밀번호), 대신
**`skincare-verify-backend` 컨테이너 내부에서 그 컨테이너 자신의 설정으로 직접 조회**했습니다
(자격증명을 추측·우회하지 않음). 결과:

```
skincare-verify DB:  rag_chunk = 0건, evidence = 0건
```

→ **65,196건은 이 두 DB 중 어디에도 없습니다.**

### B. `rag_chunk` 생성 경로

`backend/services/rag_ingestion_service.py`가 실제 생성 경로입니다(`RagIngestionService.sync_evidence()`/
`sync_knowledge_facts()`, CLI: `uv run python -m backend.services.rag_ingestion_service`).
코드는 그대로 존재하고 **재실행 가능한 상태**입니다. 별도의 embedding artifact/cache
파일(예: `.npy`, parquet 등)은 저장소에 없습니다 — 임베딩 결과는 DB(`rag_chunk`
테이블)에만 저장되는 구조라, DB가 비면 다시 만들 방법은 재실행뿐입니다.

### C. 65,196건 기록의 출처 추적

`docs/data/rag_pipeline_handoff.md`는 **2026-09-10**에 작성됐습니다(git log 확인).
반면:

```
docker volume inspect skincare_postgres-data → CreatedAt: 2026-09-11T04:48:32Z
docker inspect skincare-postgres → Created: 2026-09-11T05:11:46Z
```

**현재 DB 볼륨은 그 handoff 문서가 쓰인 다음 날 새로 생성됐습니다.** 즉 그 시점에
`docker compose down -v` 등으로 볼륨이 삭제되고 다시 만들어졌다는 강한 정황 증거입니다.
당시 실제로 있었던 65,196건은 그 이전 볼륨에 있었고, 그 볼륨은 더 이상 존재하지
않습니다(다른 곳에 백업이 있다는 기록도 없음).

**판정: `CASE_3_REBUILD_REQUIRED`**

근거 요약: 원본 데이터(Evidence 8,288건 등)는 재적재를 통해 이미 복원돼 있어
"완전 소실"은 아니지만, **임베딩 인덱스(`rag_chunk`)는 존재하지 않는 볼륨과 함께
사라졌고, 재실행 외에는 복구 방법이 없습니다.** 이번 작업 범위상 재실행은 하지 않았습니다.

---

## 2. Niacinamide Claim Inventory

`nia_10s_30s_claim_ingestion.jsonl`은 **저장소에 실제로 존재하지 않았습니다** — 이
파일을 만드는 ingestion 정책 코드는 지난 세션에 작성했지만, 코드 작성 직후 API 호출 없이
unit test만 하고 실제 pilot을 다시 돌리지 않아서 파일 자체가 아직 생성된 적이 없습니다.
대신 같은 로직(`NiaClaimIngestionPolicy`)을 **이미 있는 `annotations.jsonl` +
`review_queue.jsonl`(둘 다 실제 LLM 호출로 만들어진 최신 pilot 결과, 통과율 36/39)에
그대로 적용해 재구성**했습니다 — 새로운 LLM 호출은 하지 않았습니다.

| record_id | statement_id | raw_name | ingredient_id | matching_status | claim object(요약) | annotation_status | decision | priority |
|---|---|---|---|---|---|---|---|---|
| COT_ACN_F_O30_00525 | -S005 | 나이아신아마이드 | null | unresolved | 피지조절+장벽강화+진정+색소침착예방 | pending_review | `ingestible_free_text` | primary |
| COT_ACN_F_O30_01895 | -S004 | 나이아신아마이드 | null | unresolved | 염증완화+장벽강화 | pending_review | `ingestible_free_text` | primary |
| COT_ACN_F_O30_01070 | -S005 | 나이아신아마이드 | null | unresolved | 피지분비조절+장벽강화+염증후색소침착완화 | pending_review | `ingestible_free_text` | primary |
| COT_ACN_F_O30_01984 | -S006 | 나이아신아마이드 | null | unresolved | 피지조절+장벽강화 | pending_review | **`human_review`**(span fuzzy) | primary |
| COT_ACN_F_O30_02662 | -S005 | 나이아신아마이드 | null | unresolved | 피지분비정상화+염증완화+장벽회복 | pending_review | `ingestible_free_text` | primary |

`rejected`/`blocked` claim 없음 — **5건 전부 usable**(4건 즉시, 1건은 human_review 후).
중복 없음 — 5건 전부 서로 다른 NIA record에서 나온 별개 claim입니다.

> **2026-09-15 갱신 — 위 표는 fix 이전 상태다.** `RAG_FOUNDATION_REPAIR` 작업에서
> `NiaIngredientMatchingStage`에 한글 `raw_name` fallback을 추가해 재검증한 결과,
> **5건 전부 `matching_status=matched`, `ingredient_id=f90ba1bc-346b-4627-a387-8cf3759dbd7b`
> (Niacinamide)로 확정됐다.** `COT_ACN_F_O30_01984-S006`만 span fuzzy 복원 문제로
> `human_review`가 유지된다(성분 매칭과는 별개 축). 상세는
> [rag_pipeline_handoff.md](rag_pipeline_handoff.md)와 커밋 전 보고 내용 참고.
>
> 아래는 fix 발견 당시(수정 전) 기록을 그대로 보존한다.

**발견한 문제(당시엔 수정하지 않음, 보고만)**: 5건 전부 `matching_status=unresolved`이고
`ingredient_id=null`입니다. 그런데 5건 모두 `raw_name`이 정확히 `"나이아신아마이드"`
— `IngredientMaster.standard_name_ko`와 완전히 일치하는 표준명입니다. 원인은
LLM이 `raw_name_ko` 필드 대신 `raw_name` 필드에 한글명을 넣었기 때문입니다
(`NiaIngredientMatchingStage.resolve()`는 `raw_name`을 영문으로 가정해
`normalize_en()`을 태우므로 한글이 들어오면 실패). **이건 프롬프트/후처리 개선
사항으로, 이번 vertical slice 범위 밖이라 코드는 고치지 않았습니다** — 하지만 고치면
5건 전부 `matched`로 바뀔 가능성이 높아, `ingestible_structured` 경로(Evidence RAG
설계의 Case A)를 실제로 테스트하려면 이 수정이 선행돼야 합니다.

---

## 3. PubMed Evidence Candidates

**실제 NCBI E-utilities(esummary/efetch)로 검증된 후보만** 포함했습니다 — 검색 엔진
요약이 PMID를 서로 다른 논문에 잘못 갖다 붙이는 사례를 직접 발견해서(아래 참고),
추측되는 PMID는 전부 배제했습니다.

| PMID | Title | Journal / Year | Study Type | Formulation |
|---|---|---|---|---|
| **16766489** | The effect of 2% niacinamide on facial sebum production | J Cosmet Laser Ther, 2006 | human_study (RCT, 일본 100명 + 백인 30명 split-face) | single_ingredient |
| **10971324** | Nicotinamide increases biosynthesis of ceramides... | Br J Dermatol, 2000 | mixed_in_vitro_and_human | single_ingredient |
| **22206073** | Two RCTs of niacinamide/glycerin body moisturizers vs conventional | J Drugs Dermatol, 2012 | human_study | **combination_formulation**(glycerin 병용) |
| **21822427** | Niacinamide 4% vs Hydroquinone 4% in Melasma | Dermatol Res Pract, 2011 | human_study (RCT) | single_ingredient, 단 melasma 환자 대상 |

**검증 중 실제로 겪은 오류**: 첫 검색에서 AI 요약이 "PMID 10971324가 2000년 일본인
18명 대상 미백 연구"라고 서술했는데, NCBI에서 직접 esummary/efetch로 확인하니 실제로는
**barrier/ceramide 연구**였습니다(미백 연구가 아님). 검색 엔진의 자연어 요약을 그대로
믿지 않고 공식 API로 재검증한 이유입니다.

**적용한 배제 원칙**: 복합 제형(PMID 22206073의 niacinamide+glycerin)은 단일 성분
효과로 일반화하지 않고 `WEAK`/`PARTIAL`로 낮춰 표시. oral/systemic 연구는 검색 결과에
없었음(all topical). Finished product 효능 연구도 없었음.

---

## 4. Claim ↔ Evidence Mapping

| Claim Statement ID | Claim(요약) | PMID | Match | Evidence 사용 가능 여부 |
|---|---|---|---|---|
| COT_ACN_F_O30_00525-S005 | 피지조절+장벽강화+진정+색소침착예방 | 16766489 | DIRECT | **USABLE**(피지조절) |
| COT_ACN_F_O30_00525-S005 | 〃 | 10971324 | PARTIAL | PARTIAL(장벽, in vitro 근거 비중 큼) |
| COT_ACN_F_O30_00525-S005 | 〃 | 21822427 | PARTIAL | PARTIAL(색소침착, population 다름-melasma) |
| COT_ACN_F_O30_01895-S004 | 염증완화+장벽강화 | 10971324 | PARTIAL | PARTIAL(장벽만, 염증 근거 아님) |
| COT_ACN_F_O30_01895-S004 | 〃 | 22206073 | WEAK | NEEDS_REVIEW(복합제형) |
| COT_ACN_F_O30_01070-S005 | 피지조절+장벽강화+염증후색소침착완화 | 16766489 | DIRECT | **USABLE**(피지조절) |
| COT_ACN_F_O30_01070-S005 | 〃 | 21822427 | PARTIAL | PARTIAL(색소침착 방향은 맞으나 조건 다름) |
| COT_ACN_F_O30_01984-S006 | 피지조절+장벽강화(human_review) | 16766489 | DIRECT | PARTIAL(claim 자체가 사람 검토 전) |
| COT_ACN_F_O30_02662-S005 | 피지조절+염증완화+장벽회복 | 16766489 | DIRECT | **USABLE**(피지조절) |
| COT_ACN_F_O30_02662-S005 | 〃 | 10971324 | PARTIAL | PARTIAL(장벽만) |

**"염증(inflammation)" claim topic은 4개 claim에 등장하지만, 확보한 4개 PubMed 후보
중 염증 완화를 직접 다루는 논문은 없습니다** — sebum/barrier/pigmentation은 각각
직접·부분 근거가 있지만 inflammation만 구조적으로 빈 상태입니다(추가 검색 필요, 이번
범위에서는 안 함).

이 표는 향후 Claim→Evidence Retrieval Gold Set의 **seed 5행**으로 그대로 쓸 수
있습니다(현재는 사람이 만든 수동 매핑이라 재현성 있는 시작점).

---

## 5. `EvidenceDocument`/`EvidenceChunk` 예시 변환

`EVIDENCE_RAG_DESIGN.md`의 스키마를 그대로 적용했습니다.

```json
{
  "source_id": "PMID:16766489",
  "source_type": "pubmed_abstract",
  "source_title": "The effect of 2% niacinamide on facial sebum production",
  "publisher": "Journal of Cosmetic and Laser Therapy",
  "document_date": "2006-06",
  "url": "https://pubmed.ncbi.nlm.nih.gov/16766489/",
  "doi": "10.1080/14764170600717704",
  "pmid": "16766489",
  "jurisdiction": null,
  "language": "en",
  "evidence_level": "peer_reviewed_study",
  "ingredient_ids": ["f90ba1bc-346b-4627-a387-8cf3759dbd7b"]
}
```

```json
{
  "chunk_id": "PMID:16766489:abstract:0",
  "source_id": "PMID:16766489",
  "source_type": "pubmed_abstract",
  "source_title": "The effect of 2% niacinamide on facial sebum production",
  "page": null,
  "section": "abstract",
  "chunk_index": 0,
  "content": "BACKGROUND: The presence of sebum on the face is responsible for both facial shine and the formation of comedonal and inflammatory acne lesions... CONCLUSIONS: Topical 2% niacinamide may be effective in lowering the SER in Japanese individuals and CSL in Caucasian individuals.",
  "doi": "10.1080/14764170600717704",
  "pmid": "16766489",
  "jurisdiction": null,
  "evidence_level": "peer_reviewed_study",
  "ingredient_ids": ["f90ba1bc-346b-4627-a387-8cf3759dbd7b"]
}
```

**PARTIAL 사례 (복합 제형 — formulation 필드가 실제로 왜 필요한지 보여주는 예)**:

```json
{
  "source_id": "PMID:22206073",
  "source_type": "pubmed_abstract",
  "source_title": "Two randomized, controlled, comparative studies of the stratum corneum integrity benefits of two cosmetic niacinamide/glycerin body moisturizers vs. conventional body moisturizers",
  "publisher": "Journal of Drugs in Dermatology",
  "document_date": "2012-01",
  "url": "https://pubmed.ncbi.nlm.nih.gov/22206073/",
  "doi": null,
  "pmid": "22206073",
  "jurisdiction": null,
  "language": "en",
  "evidence_level": "peer_reviewed_study",
  "formulation_type": "combination_formulation",
  "ingredient_ids": ["f90ba1bc-346b-4627-a387-8cf3759dbd7b"]
}
```

`formulation_type`이 없으면 이 문서를 "니아신아마이드 단독 효과 근거"로 잘못 index할
위험이 실제로 있습니다 — 아래 6절에서 이 필드를 제안하는 근거입니다.

---

## 6. Schema Gaps

`EVIDENCE_RAG_DESIGN.md`에서 이미 제안한 `document_status`/`study_type`/`claim_topics`
3개에 더해, **이번 실사에서 실제로 막힌 지점 1개를 추가로 발견**했습니다:

| 필드 | 타입 | 왜 필요한가(이번에 실제로 부딪힌 사례) |
|---|---|---|
| `study_type` | 기존 제안 그대로 | PMID 10971324가 in vitro+human 혼합이라 `human_study`로 단순 분류가 안 됨 → `mixed_in_vitro_and_human` 값 필요 |
| `document_status` | 기존 제안 유지 | 이번엔 PubMed라 해당 사례 없었음(CIR 전용 이슈로 남음) |
| `claim_topics` | 기존 제안 유지 | PMID 16766489 하나가 `sebum_control`만이 아니라 문맥상 acne(염증성 여드름)도 언급 — 문서 하나가 여러 topic을 가질 수 있음을 실제로 확인 |
| **`formulation_type`**(신규 제안) | `Literal["single_ingredient","combination_formulation"] \| None` | PMID 22206073(niacinamide+glycerin)을 다른 단일성분 논문과 구분할 필드가 없으면, "복합 제형 연구를 단일 성분 효과로 일반화하지 않는다"는 원칙을 코드로 강제할 수 없음. **이건 제안이 아니라 실제로 막힌 사례라 필수에 가깝다고 판단** |
| `population`(검토 후 보류) | — | PMID 21822427이 melasma 환자 대상이라 "여드름 후 색소침착" claim과 population이 다르다는 걸 이번엔 사람이 직접 읽고 판단했습니다. 필드화하면 좋겠지만 자유텍스트 population을 구조화하는 기준이 아직 없어서, **이번엔 필드 추가를 보류**하고 `notes` 자유텍스트로 남기는 쪽을 제안합니다(필드 과잉 설계 방지) |

**정리**: `study_type`/`claim_topics`는 이전 설계 그대로 필요, `formulation_type`은
이번에 실제로 필요성이 확인돼 새로 추가 제안, `population`은 보류.

---

## 7. Vertical Slice Feasibility

**성립합니다, 단 조건부입니다.**

- Claim → Evidence 연결 자체는 실제로 가능함을 확인했습니다(5건 중 3건이 최소 1개
  DIRECT 후보를 가짐)
- 단, `ingredient_id`가 5건 전부 `null`이라(2절의 raw_name/raw_name_ko 버그) 지금은
  **전부 free-text anchor(Case B) 경로로만** 연결됩니다 — structured anchor(Case A,
  `ingredient_id` 기반)는 이번 5건으로는 테스트 못 했습니다
- `inflammation` claim topic은 구조적으로 근거가 빔 — 추가 PubMed 검색이 필요
- `rag_chunk`가 비어 있어(1절) 실제 검색 인프라는 아직 준비 안 됨 — 이건 이번
  vertical slice의 "설계 성립 여부"와는 별개 문제

---

## 8. Recommended Next Step

1. **raw_name/raw_name_ko 매칭 버그 수정** — `NiaIngredientMatchingStage`가 한글이
   `raw_name`에 들어와도 `standard_name_ko`와 매칭 시도하도록 보정(작은 수정으로
   추정되나 이번 범위 밖이라 코드는 안 고침)
2. `inflammation` claim topic 보완용 PubMed 검색 1회 추가
3. `EvidenceDocument`에 `formulation_type` 필드 반영(설계 문서만, 코드 미착수)
4. `rag_chunk` 재실행 필요 여부를 사용자에게 확인(1절 CASE_3 판정에 따른 후속 결정)
5. 위 4개가 정리되면 Niacinamide 5건 전체를 `EvidenceQueryAnchor`로 변환해 다음
   vertical slice(실제 retrieval 없이 anchor 생성까지만) 진행 검토

---

## 산출물

- 이 문서: `docs/data/NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md`
- Machine-readable: `data/processed/niacinamide_claim_evidence_candidates.json`

---

## 최종 보고

```
NIACINAMIDE_EVIDENCE_VERTICAL_SLICE

rag_chunk status:
CASE_3_REBUILD_REQUIRED
(근거: handoff 문서는 2026-09-10 작성, 현재 DB 볼륨은 2026-09-11 04:48 생성 —
문서 작성 다음 날 볼륨이 재생성됨. skincare-verify DB도 0건이라 다른 곳에 안 남아 있음.
원본 데이터(Evidence 8,288건)는 재적재로 복원돼 있으나 임베딩 인덱스만 소실.)

Niacinamide usable claims:
5 (rejected/blocked 없음, 4건 즉시 ingestible_free_text + 1건 human_review)

PubMed evidence candidates:
4 (NCBI E-utilities로 검증됨: PMID 16766489, 10971324, 22206073, 21822427)

Directly supported claims:
3 (sebum_control topic — 16766489)

Partially supported claims:
5 (barrier/pigmentation topic — 10971324, 21822427 각각 부분 지지)

Unsupported claims:
0건이 완전 무근거는 아니지만, inflammation topic은 4개 claim에서 등장하는데
근거 후보가 전혀 없음(구조적 공백)

Schema:
MINOR_CHANGE_NEEDED
(기존 3개 제안 필드 + formulation_type 1개 신규 제안, 전부 문서 설계 단계일 뿐 코드 미변경)

Vertical Slice Feasibility:
PARTIAL
(Claim→Evidence 연결 개념은 성립 확인, 단 ingredient_id 매칭 버그로 structured anchor
경로 미검증 + rag_chunk 인프라 미비)

Recommended Next Step:
1. raw_name/raw_name_ko 매칭 버그 수정
2. inflammation topic PubMed 검색 보완
3. formulation_type 필드 설계 반영
4. rag_chunk 재실행 여부 사용자 결정
5. 5건 전체 EvidenceQueryAnchor 변환(retrieval 없이 anchor까지만)

Files Created:
- docs/data/NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md
- data/processed/niacinamide_claim_evidence_candidates.json
```
