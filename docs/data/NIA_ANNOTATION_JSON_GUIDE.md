# NIA 정제 데이터(JSON) 구조 설명 — 팀원용

> 대상 파일: `data/processed/nia_10s_30s_annotations.jsonl`
> 한 줄 = `NiaLabelingDocument` 하나(= NIA raw record 하나를 의미 라벨링한 결과)
> 스키마 정의: `data/manual_review/nia_labeling_schemas.py` (고정, 임의 변경 금지)
> 검증기: `data/manual_review/nia_labeling_parser.py`

## 0. 이 데이터가 뭔가

NIA AI Hub CoT 원문(질문+답변+추론과정)을 LLM으로 의미 단위(`statement`)로 쪼갠 결과입니다. **과학적 근거 문서가 아니라 "사용자 고민과 성분/효능/주의사항이 어떻게 연결되어 언급됐는가"를 구조화한 claim 계층**입니다. 실제 과학적 근거(CIR/MFDS/논문)는 별도의 Evidence RAG가 담당합니다.

현재 39건 pilot 결과이며(`docs/data/POC_DATASET_HANDOFF.md`, `EVIDENCE_RAG_DESIGN.md` 참고), 전체 3,581건 확장은 아직 안 된 상태입니다.

---

## 1. 최상위 구조

```json
{
  "schema_version": "1.1",
  "annotation_version": "llm-pilot-2026-09-14-openai-gpt-4o-mini",
  "is_example": false,
  "is_partial_annotation": true,
  "production_ready": false,
  "annotator_count": 1,
  "source": { ... },
  "case_context": { ... },
  "statements": [ ... ],
  "references": [ ... ],
  "notes": ["LLM 자동 라벨링 결과, 사람 검토 전(pending_review)."]
}
```

| 필드 | 의미 |
|---|---|
| `annotation_version` | 어떤 provider/model로 만들어졌는지 문자열에 포함됨(예: `-openai-gpt-4o-mini`). Qwen 등으로 다시 돌리면 값이 달라지므로 **결과를 섞어서 비교하지 말 것** |
| `production_ready` | **항상 `false`.** 사람 최종 승인 전이라는 뜻. 이 값이 `true`인 문서는 아직 없음 |
| `is_partial_annotation` | 7개 statement type을 전부 채우지 않았다는 뜻(원문에 실제로 있는 것만 추출하므로 정상) |

---

## 2. `source` — 원본 위치

```json
"source": {
  "kind": "training_zip_record",
  "record_id": "COT_ACN_F_O30_00319",
  "source_archive": "TL_미백(색소침착_기미_칙칙함).zip",
  "source_hash": null,
  "dataset_split": "training",
  "info_target_concern": "여드름/뾰루지",
  "archive_name_target_concern_mismatch": true
}
```

- `record_id`: NIA 원본 jsonl의 `info.id`. 이 값으로 `data/processed/nia_qa_10s_30s.jsonl`에서 원문을 다시 찾을 수 있음
- `dataset_split`: `training`/`validation`. **절대 섞지 말 것** — retrieval 평가 시 validation이 index에 들어가면 안 됨
- `archive_name_target_concern_mismatch`: **위 예시처럼 `true`인 경우가 꽤 흔함**(zip 파일명은 "미백"인데 실제 내용은 "여드름"). zip 파일명을 신뢰하지 말고 `info_target_concern`이나 아래 `case_context.skin_concerns_raw`를 기준으로 쓸 것

## 3. `case_context` — 사례 프로필

```json
"case_context": {
  "age_raw": 33,
  "age_text_raw": "33세",
  "gender_raw": "여성",
  "skin_type_raw": "복합성",
  "skin_concerns_raw": ["여드름/뾰루지", "미백(색소침착/기미/칙칙함)"],
  "initial_skin_condition_raw": "S/P1/W0/A/NVP/NSA/ND/R"
}
```

피부 고민 검색 필터링에 쓸 수 있는 필드들. `skin_concerns_raw`는 다중 라벨(배열)이라는 점 주의.

---

## 4. `statements[]` — 핵심 데이터

7개 타입이 있고, **case_observation / ingredient_effect_claim / precaution / usage_instruction 4종이 Claim RAG 우선 대상**입니다(나머지 3종은 있으면 쓰되 완벽할 필요 없음).

### 공통 필드 (모든 statement)

| 필드 | 의미 |
|---|---|
| `statement_id` | `{record_id}-S{번호}` 형식 |
| `source_spans[]` | `json_path`(원문 위치) + `quote`(원문 리터럴 그대로) + `start`/`end`(유니코드 코드포인트 오프셋). **quote는 반드시 원문의 정확한 부분 문자열** — 재검증 가능 |
| `annotation_status` | `pending_review`(기본) / `approved` / `rejected`. **`rejected`는 quote가 statement 내용과 의미적으로 안 맞아서 자동으로 걸러진 것** — 이 값이 rejected면 쓰지 말 것 |
| `support_status` | 항상 `unverified`. 과학적 검증 여부와 무관한 필드(이 라벨링 자체가 원문을 얼마나 정확히 옮겼는지와, 그 내용이 과학적으로 맞는지는 별개) |
| `note` | LLM이 남긴 참고 메모(있을 때만) |

### 4-1. `case_observation` — 사례가 보고하는 고민

```json
{
  "statement_type": "case_observation",
  "subject": "여드름/뾰루지 발생"
}
```

### 4-2. `ingredient_effect_claim` — 성분 효능 주장 ★가장 중요

```json
{
  "statement_type": "ingredient_effect_claim",
  "subject": {
    "raw_name": "호스래디시뿌리추출물",
    "raw_name_ko": null,
    "ingredient_id": null,
    "matching_status": "unresolved"
  },
  "object": "여드름 완화",
  "concentration_raw": null
}
```

- `subject.matching_status`: `matched`(RDB의 `IngredientMaster`와 확정 연결) / `unresolved`(원문 표현 그대로만 있음) / `unresolved_ambiguous_family`(원문이 계열명·여러 INCI 병기라 단일 성분 확정 불가) / `rejected`
- **`matched`일 때만 `ingredient_id`가 채워짐.** fuzzy 매칭은 자동으로 `matched`가 되지 않음 — 성분명 표준화 매칭이 deterministic(exact/정규화 일치)하게 확정될 때만
- `unresolved`여도 `raw_name`으로 free-text 검색은 가능(Evidence RAG 설계 문서의 Case B 참고)

### 4-3. `precaution` — 주의사항

```json
{
  "statement_type": "precaution",
  "subject": "여드름을 손으로 짜거나 만지지 말 것",
  "relation": "avoid"
}
```

`relation`: `avoid`(하지 말 것) / `possible_irritation`(자극 가능성).

### 4-4. `usage_instruction` — 사용법

```json
{
  "statement_type": "usage_instruction",
  "action_id": "A001",
  "action": "세안은 하루 두 번 순하고 약산성 클렌저를 사용",
  "time_of_day": [],
  "frequency": null,
  "ingredient_ids": []
}
```

- `time_of_day`(`morning`/`evening`/`daytime`/`night`)와 `frequency`(`{min, max, period}`)는 **원문에 명시적으로 있을 때만 채워짐** — 위 예시처럼 비어 있는 경우가 실제로 많음(원문 자체에 시간/빈도 언급이 없거나, 있어도 정규식이 못 잡은 경우가 섞여 있어 표본을 더 볼 필요가 있음. `POC_DATASET_HANDOFF.md`에 관찰 기록됨)
- `action_id`가 같으면 같은 행동(예: 아침/저녁 span이 따로 있어도 하나로 합쳐짐), 다르면 별개 행동

### 4-5. `cause_claim` / `contextual_factor` / `combination_claim` — 보조 정보

핵심 4종이 아니므로 coverage가 낮아도 파이프라인을 더 확장하지 않기로 함. 필드는 스키마 파일(`nia_labeling_schemas.py`) 참고.

---

## 5. `references[]` — 원문 인용 (⚠ claim과 자동 연결 안 됨)

```json
"references": [
  {"raw": "DOI:10.1016/j.clindermatol.2017.02.008", "reference_status": "unverified", "statement_links": []},
  {"raw": "PMID:24706598", "reference_status": "unverified", "statement_links": []}
]
```

- `statement_links`는 **의도적으로 항상 빈 배열**입니다. NIA 원문 구조상 "이 논문이 이 statement의 근거"라고 판단할 위치 정보가 없어서, 잘못된 연결(false positive)을 만들지 않기로 결정했습니다
- `reference_status=placeholder_detected`면 `DOI:10.xxxx/xxxxx` 같은 가짜 placeholder(실제 8,000건 중 다수가 이런 형태로 확인됨) — 실제 문헌 취급하면 안 됨. `unverified`도 형식만 정상이고 실제 문헌 대응은 검증 안 된 상태
- **claim의 실제 과학적 근거는 이 필드가 아니라 별도 Evidence RAG(`EVIDENCE_RAG_DESIGN.md`)가 검색해서 연결합니다**

---

## 6. 관련 산출물 파일

| 파일 | 내용 |
|---|---|
| `nia_10s_30s_annotations.jsonl` | 이 문서가 설명하는 파일. parser 검증을 통과한 문서만 |
| `nia_10s_30s_labeling_failures.jsonl` | 라벨링/검증 실패 기록(`record_id`, 실패 단계, 에러) |
| `nia_10s_30s_review_queue.jsonl` | 통과했지만 사람이 볼 사유가 있는 문서. `blocking_reasons`(claim 신뢰성 문제)와 `non_blocking_reasons`(품질 메타데이터일 뿐, 사용에 지장 없음)로 분리돼 있음 |
| `nia_10s_30s_claim_ingestion.jsonl` | **statement별로 "지금 Claim RAG에 써도 되는가"를 이미 판정해 둔 파일.** `decision`(`ingestible_structured`/`ingestible_free_text`/`human_review`/`blocked`)과 `priority`(`primary`=핵심4종/`secondary`)가 있음. **retrieval 구현 시 이 파일을 기준으로 index 대상을 고르면 됨** — `review_queue`에 있다고 무조건 제외하면 안 됨 |

## 7. 주의할 점 정리

1. `production_ready=false`는 전부 동일 — 사람 최종 검토 전이라는 뜻이지 "쓰지 마라"는 아님
2. `annotation_status=rejected`인 statement만 실제로 제외 대상(위 claim ingestion 파일의 `blocked`와 대응)
3. `dataset_split` 섞지 말 것
4. `ingredient_id`는 deterministic 매칭된 것만 채워짐 — 없다고 성분이 틀린 게 아니라 raw_name으로 free-text 검색하면 됨
5. 이건 **pilot(39건)** 데이터입니다 — 전체 3,581건 확장 여부는 아직 결정 안 됨
