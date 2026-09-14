# POC 데이터셋 전달 문서

> 목적: 팀원이 아래 3개 데이터셋을 다시 구조를 해석하지 않고 바로 쓸 수 있게 한다.
> RAG retrieval·임베딩·추천·agent 구현은 이 작업 범위 밖이다 — 여기서는 **데이터까지만** 만든다.

## 사용처 요약

```
ingredient 데이터  → RDB direct lookup (성분 표준명/식별자 조회)
product 데이터     → RDB product candidate lookup (제품 후보 조회)
NIA annotation 데이터 → RAG retrieval source (아직 미적재, 구조만 준비됨)
```

---

## A. Ingredient — `data/processed/ingredient_full.csv`

### Contract

| 항목 | 값 |
| --- | --- |
| Primary key | `ingredient_id` (UUID, `IngredientMaster.id`) |
| 성분명 필드 | `standard_name_ko`, `standard_name_en` |
| Alias 필드 | `old_names_ko`, `old_names_en` (둘 다 `\|` 구분 문자열) |
| Lookup 방법 | `standard_name_ko` 또는 `standard_name_en`으로 exact match 우선, 없으면 `old_names_*`도 확인. Fuzzy match는 이 CSV 자체에 없음(원본 DB 매칭 단계에서만 씀) |
| 지식 필드 | `knowledge_*` (효능·권장피부타입·주의사항·권장농도·규제신뢰도) — `IngredientKnowledgeFact` 매칭된 2,399건만 채워짐, 나머지는 빈 문자열 |
| 근거 필드 | `evidence_count`, `evidence_jurisdictions`, `evidence_claims` — MFDS 등 공식 근거. 여러 건이면 `\|`로 이어붙임 |

### 생성 방법 (재실행 가능)

```bash
uv run python -m data.scripts.export_ingredient_dataset
```

RDB(`IngredientMaster` + `IngredientKnowledgeFact` + `Evidence`)에서 직접 조회한다. RAG/LLM을 거치지 않는다.

### 품질 지표

| 지표 | 값 |
| --- | --- |
| 전체 성분 수 | 21,974 |
| `standard_name_en` 결측률 | 5.7% |
| Alias(`old_names_ko`/`old_names_en`) 보유율 | 18.9% |
| 지식데이터(`knowledge_inci_name`) 매칭률 | 10.9% (2,399/21,974) — Knowledgedata.xlsx가 애초에 2,465개 성분만 다룸 |
| 근거(`evidence_claims`) 보유율 | 6.3% (MFDS 매칭 결과, 원본 낮은 매칭률은 알려진 정상 현상 — `docs/data/data.md` 참고) |
| `ingredient_id` 중복 | 0건 |

---

## B. Product — `data/processed/product_candidates.csv` + 2개 파생 파일

### Contract

| 항목 | 값 |
| --- | --- |
| Primary key | `(source, source_product_id)` — `candidate_id`는 재수집마다 바뀔 수 있어 식별자로 쓰지 않는다 |
| 추천에 쓸 필드 | `display_title`, `brand`, `lowest_price`/`highest_price`/`price_band`, `category1~3`, `product_type_normalized`/`service_category`, `image_url`, `shopping_url` |
| Ingredient relation 사용법 | `product_ingredient_mapping.csv`를 `(source, source_product_id)`로 join. `ingredient_id`가 있는 행만 확정 매칭 |
| excluded/review_required 의미 | 아래 "품질 분류" 참고. **excluded 상품은 추천 후보에서 제외**, review_required는 "쓸 수는 있지만 확인 필요" |

### `product_ingredient_mapping.csv` (신규)

전성분 원문(`raw_ingredients_text`)을 `ProductIngredientTextParser`로 토큰화한 뒤, 각 토큰을 ingredient master와 **deterministic 매칭만**(표준명/구명칭 exact·정규화 일치, fuzzy 제외) 연결한 결과.

| 컬럼 | 설명 |
| --- | --- |
| `candidate_id`, `source`, `source_product_id`, `target_group` | 원본 상품 식별 |
| `raw_token` / `matching_name` | 전성분 원문 토큰 / 매칭용으로 정규화한 이름 |
| `ingredient_id` | 확정 매칭된 경우만 채움. 비어있으면 `unresolved` |
| `matching_status` | `matched` \| `unresolved` |
| `match_method` | 어떤 규칙으로 매칭됐는지(`standard_name_en_normalized` 등) |

### `product_quality_report.csv` (신규)

| status | 의미 |
| --- | --- |
| `valid` | 바로 써도 됨 |
| `review_required` | 아래 `reasons`(`\|` 구분) 중 하나 이상 해당 — 전성분 없음, `review_reasons` 존재, 중복 후보 행, `target_group`이 실제 매칭 성분에서 확인 안 됨 |
| `excluded` | `match_status=rejected` — 추천 후보에서 제외 |

### 생성 방법

```bash
uv run python -m data.scripts.build_product_datasets
```

### 품질 지표

| 지표 | 값 |
| --- | --- |
| 전체 상품 후보 | 96건 (고유 `source_product_id` 93개) |
| `valid` / `review_required` / `excluded` | 77 / 19 / 0 |
| review 사유 분포 | `target_group_not_confirmed_in_ingredients` 11건, 기존 `review_reasons`(옵션 모호 등) 15건, 전성분 결측 1건 |
| 전성분 토큰 → ingredient 매칭률 | 94.8% (5,182 / 5,464 토큰, deterministic만) |
| 핵심 성분 5종 valid 상품 수 | Vitamin C 19, Niacinamide 28, Retinol 25, AHA(Glycolic) 3, BHA(Salicylic) 2 — **AHA/BHA는 표본이 얇음**(각 3건/4건), 실서비스 추천에는 부족할 수 있음 |

---

## C. NIA — `data/processed/nia_10s_30s_*.jsonl`

### Contract (`NiaLabelingDocument`, `data/manual_review/nia_labeling_schemas.py` 그대로 사용)

| 필드 | 의미 |
| --- | --- |
| `source.record_id` | NIA 원본 레코드 ID (`info.id`) |
| `source.dataset_split` | `training` \| `validation` — **절대 섞지 않는다.** `nia_structural_audit_9000.jsonl`에서 join해 보강함(원본 zip 재파싱 없음) |
| `case_context` | `age_raw`, `skin_type_raw`, `skin_concerns_raw` 등 — retrieval 필터링에 쓸 수 있음 |
| `statements[].statement_type` | 7종 중 원문에 실제로 있는 것만. `case_observation`/`ingredient_effect_claim`/`precaution`이 1차 POC 핵심 |
| `statements[].source_spans` | `json_path`/`quote`/`start`/`end` — 전부 원문 재검증 가능(LLM이 offset을 직접 만들지 않음) |
| `ingredient_effect_claim.subject` / `combination_claim.subjects` | `{raw_name, raw_name_ko, ingredient_id, matching_status}`. `matching_status=matched`일 때만 `ingredient_id`가 채워짐(fuzzy 제외, deterministic만) |
| `support_status` | 전부 `unverified` — 과학적 검증 여부와 무관, semantic annotation일 뿐 |
| `production_ready` | 전부 `False` — 사람 최종 승인 전 |

### 검색 흐름 (retrieval 설계 시 참고)

```
피부 고민 텍스트
  → case_observation.subject / case_context.skin_concerns_raw 로 후보 문서 검색
  → 같은 record의 ingredient_effect_claim 조회
  → subject.ingredient_id (matched인 것만)
  → ingredient_full.csv / IngredientMaster RDB lookup
```

### 생성 방법 (pilot 규모, 체크포인트 지원)

```bash
uv run python -m data.scripts.nia_pilot_runner
```

`data/processed/nia_qa_10s_30s.jsonl`(3,581건, 10~30대만)에서 구조 감사(`nia_structural_audit_9000.jsonl`)의 `risk_level` 분포를 따라 39건을 층화 추출해 LLM 라벨링 → deterministic ingredient 매칭 → `NiaLabelingParser` 검증까지 실행한다. 중단 시 `.nia_10s_30s_pilot_checkpoint.txt` 기준으로 이미 처리한 `record_id`를 건너뛴다(단, 이번 pilot은 매 실행마다 결과 파일을 새로 씀 — 이어달리기가 아니라 재검증용).

### Pilot 결과 (39건 시도, 2026-09-14)

| 지표 | 값 |
| --- | --- |
| 시도 | 39건 |
| **Parser(schema+span+invariant) 통과** | **7건 (18%)** |
| 실패 | 32건, **전부 "labeling" 단계**(LLM이 반환한 quote가 원문과 완전히 일치하지 않음) — parser 검증(schema/invariant) 자체에서 떨어진 건 0건 |
| Review queue | 7건 (통과했지만 성분 unresolved 등 검토 필요) |
| 통과 문서의 statement 평균 | 3.43개/문서 |
| statement_type 분포(통과분) | `case_observation` 7, `ingredient_effect_claim` 10, `usage_instruction` 3, `precaution` 2, `cause_claim` 2 — **1차 POC 핵심 3종 모두 안정적으로 나옴** |
| `support_status` | 전부 `unverified` (설계대로) |
| ingredient matching(통과분) | matched 9, unresolved 1, ambiguous_family 0 |
| placeholder reference | 이번 pilot 표본에는 미등장(9,000건 감사 기준 전체의 37%가 placeholder) |

**실패 원인 분석**: LLM이 `chain_of_thought[i].content`의 배열 인덱스 `i`를 원본의 `step`(1부터 시작하는 필드)과 혼동해, 실제로는 다른 인덱스에 있는 문장을 잘못된 경로로 인용하는 systematic 오류가 확인됨. 1차 수정으로 "같은 배열의 다른 인덱스에서 quote를 재탐색"하는 fallback을 span builder에 추가해 통과율이 0% → 18%로 개선됐지만, quote 자체가 원문과 글자 단위로 다른 경우(패러프레이즈)는 여전히 실패로 남는다 — **의도된 동작**(원문 밖 내용을 만들지 않는다는 규칙을 지키는 것이 목적이므로 관대하게 통과시키지 않음).

---

## 산출물 파일 목록

```
data/processed/ingredient_full.csv                    (21,974행)
data/processed/product_candidates.csv                  (96행, 기존 파일 — 수정 없음)
data/processed/product_ingredient_mapping.csv           (5,464행, 신규)
data/processed/product_quality_report.csv               (96행, 신규)
data/processed/nia_qa_10s_30s.jsonl                     (3,581건, 원본 raw corpus)
data/processed/nia_10s_30s_annotations.jsonl            (7건, parser 통과분 — pilot 규모)
data/processed/nia_10s_30s_labeling_failures.jsonl      (32건)
data/processed/nia_10s_30s_review_queue.jsonl           (7건)
```

## 전체 3,581건 확장 전에 남은 이슈

1. **LLM quote 정확도**: 18% 통과율로는 3,581건 전체 실행 시 review 물량이 매우 커진다. 재시도(같은 record를 다른 프롬프트/온도로 재시도) 로직이 아직 없음 — 지금은 1회 시도 후 바로 실패로 기록한다.
2. **비용/시간**: gpt-4o-mini 기준 39건에 수 분 소요. 3,581건이면 단순 비례로도 상당한 시간·비용이 들고, 재시도 로직을 넣으면 더 늘어난다.
3. **AHA/BHA 상품 표본이 얇음**(3건/4건) — 실제 추천에 쓰기엔 부족해 보이므로 상품 수집 확대가 필요할 수 있음.
4. **`product_taxonomy_backfill.py`**: 최근 main 병합 시 taxonomy 설계가 단순화되면서 이 스크립트의 존재 이유(로컬 전용 백필 계약)가 문서에서 빠졌다 — 이번 작업 범위 밖이라 그대로 두었지만, 정리가 필요하면 별도로 확인 요청.
