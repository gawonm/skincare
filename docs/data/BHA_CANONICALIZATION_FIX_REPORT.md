# BHA Canonicalization Fix Report

## STEP 1 — 영향범위 확인 (read-only, canonical v5 기준)

### 1) literal "BHA" ingredient_master row

| 필드 | 값 |
| --- | --- |
| `id` | `e48d0911-3e9a-4aa4-b013-8b10c3931548` |
| `ingredient_code` | 718 |
| `standard_name_ko` | 비에이치에이 |
| `standard_name_en` | BHA |
| `normalized_name_ko` | 비에이치에이 |
| `normalized_name_en` | bha |
| `old_names_ko` / `old_names_en` | `{}` / `{}` (둘 다 빈 배열) |
| `source_version` | 2026-08-31 |

`ingredient_master`의 21,974개 행 중 하나로, 별도 오류 삽입이 아니라 원본
성분 마스터 소스에 실제로 "BHA"라는 표기가 그대로 한 행으로 들어있는
것이다.

### 2) 참조 row 수(canonical v5 기준)

| 테이블 | 건수 |
| --- | --- |
| `product_ingredient` (전체) | 8 |
| `product_ingredient` (`match_acceptance='confirmed'`) | 8 |
| `evidence_chunk_ingredient` | 0 |
| `ingredient_knowledge_fact` | 1 |
| `evidence`(legacy MFDS) | 0 |
| `claim_chunk_ingredient` | 0 |
| `rag_chunk` | 0 |

8개 제품의 실제 성분표 원문 토큰이 구체 화학명으로 분해되지 않고 "BHA"
그대로 남아 이 행에 confirmed 매칭돼 있다. `ingredient_knowledge_fact` 1건은
"efficacy: 살리실산과 같은 지용성 각질 제거제..." 식으로 이 행 자체가
비특정(구체 화학종 미상) 원료임을 이미 시사하는 내용이다. NIA/case 관련
테이블에는 `ingredient_master`를 직접 참조하는 FK가 없다(`information_schema`
조회로 `claim_chunk_ingredient`, `evidence_chunk_ingredient`, `evidence`,
`ingredient_knowledge_fact`, `product_ingredient`, `rag_chunk` 6개만 확인).

### 3) Salicylic Acid / Betaine Salicylate canonical IDs

| 성분 | `id` | 수정 전 `old_names_en` |
| --- | --- | --- |
| Salicylic Acid(살리실릭애씨드) | `5c3fa47f-b797-452c-bc86-04a872aa3f71` | `{}` |
| Betaine Salicylate(베타인살리실레이트) | `8e64999b-9767-4ab0-9abf-1230a8e07668` | `{}` |

### 4) `INGREDIENT_ALIAS_RESOLUTION_PLAN.md`의 BHA 관련 설계

이 계획 문서는 **BHA 문제를 다루지 않는다.** 공백/정규화 문제(예: "알로에
베라 잎즙 파우더" 같은 공백 차이로 인한 `NO_RESULTS`)만 다루며, 8절
"구현 비범위"에 **"`ingredient_master` 데이터 수정 또는 구명칭 배열
보강"을 명시적으로 이번 Agent 계획 범위 밖**으로 못박아 뒀다. 즉 이
문서와 이번 Data 수정은 서로 다른 문제를 다루고 있어 충돌하지 않는다.
다만 5절의 계약은 그대로 유효하다: "서로 다른 표준 성분이 둘 이상: `SUCCESS`와
`ambiguous_candidates`; Agent가 임의 선택하지 않음" — 이 계약이 정확히
이번 Data 수정이 기대는 기존 메커니즘이다.

### 5) 기존에 이미 있는 alias/ambiguity 구조

- **DB 레벨(existing, 데이터만으로 활용 가능)**:
  `backend/repositories/agent_ingredient_repository.py::AgentIngredientReadRepository.find_exact()`가
  `standard_name_ko/en`, `normalized_name_ko/en`, **`old_names_ko`/`old_names_en`
  배열**까지 전부 정확 일치로 조회하고, **일치 행이 2개 이상이면 그대로
  반환**한다. 그 결과를 받는
  `backend/services/two_layer_rag_adapters.py::TwoLayerIngredientRepository.resolve()`는
  "정확히 1건 -> `SUCCESS`+`ingredient`, 2건 이상 -> `SUCCESS`+`ambiguous_candidates`"로
  이미 분기한다 - **코드를 전혀 고치지 않고, `old_names_en` 배열에 값만
  추가해도 이 기존 분기를 그대로 이용해 모호 처리를 만들 수 있다.**
- **Agent 레벨(code, 이번 수정과 무관, 손대지 않음)**:
  `agent/rag/retrieval/ingredient_alias_mapper.py::CommonIngredientAliasMapper`가
  이미 "BHA"를 `AMBIGUOUS_FAMILY`(후보: 살리실릭애씨드, 베타인살리실레이트)로
  하드코딩해 두고 있다 - 다만 이번 E2E에서 실제로 호출되는
  `TwoLayerIngredientRepository.resolve()` 경로에서는 이 매퍼를 거치지 않고
  DB exact match가 먼저/대신 적용돼 literal BHA row가 그대로 확정됐던 것이
  근본 원인이었다(Agent 코드 흐름 자체는 이번 수정 범위 밖이라 변경하지 않음).

## STEP 2 — 선택한 수정안

**Option A**(기존 schema/데이터 contract만 사용)를 그대로 적용했다.

- `ingredient_master.old_names_en`(이미 있는 배열 컬럼)에 `'BHA'`를
  Salicylic Acid, Betaine Salicylate 두 행에 각각 추가했다.
- 새 컬럼/테이블/마이그레이션 없음. literal BHA row(`e48d0911-...`)는
  **삭제하지도 이름을 바꾸지도 않았다** - 8건의 실제 product 링크와
  1건의 knowledge_fact가 그대로 유효한 채로 남는다.
- 결과적으로 `find_exact("BHA")`는 이제 3건(Salicylic Acid, Betaine
  Salicylate, literal BHA 자신)을 반환하고, `resolve()`는 이를
  `ambiguous_candidates`로 처리한다 - literal BHA가 **단독 confirmed
  canonical ingredient로 선택되지 않는다.**
- Salicylic Acid나 Betaine Salicylate로 강제 단일 매핑하지 않았다(둘 다
  여전히 모호 후보 집합의 일원일 뿐, 어느 쪽도 자동 선택되지 않음).

## STEP 3 — 회귀 테스트 결과(실제 production 코드 호출, read-only 대상 DB)

`backend/services/two_layer_rag_adapters.py::TwoLayerIngredientRepository.resolve()`를
그대로 호출해 확인했다(Agent/Backend 코드는 호출만, 수정 없음).

| 질의 | 결과 |
| --- | --- |
| `BHA` | `status=success`, **`ingredient=None`**(단독 확정 없음), `ambiguous_candidates=[베타인살리실레이트, 비에이치에이, 살리실릭애씨드]` (3건) |
| `살리실릭애씨드` | `status=success`, `ingredient=살리실릭애씨드`, `ambiguous_candidates=[]` — 기존과 동일 |
| `베타인살리실레이트` | `status=success`, `ingredient=베타인살리실레이트`, `ambiguous_candidates=[]` — 기존과 동일 |
| `Niacinamide`, `Retinol`, `Ascorbic Acid`, `Panthenol`, `Tranexamic Acid` | 전부 기존과 동일하게 단일 확정, ambiguous 없음 — 무관 성분 regression 없음 |

## STEP 4 — DB 반영

DB mutation이 필요했다(`ingredient_master` 2개 행의 `old_names_en` 배열
갱신). canonical v5를 직접 덮어쓰지 않고, v5를 복원한 별도 임시 DB에
반영한 뒤 새 dump를 만들었다.

### Post-write counts(수정 전후 비교, 전부 v5와 동일 - 행 추가/삭제 없음)

| 테이블 | 값 |
| --- | --- |
| `ingredient_master` | 21,974 (변동 없음, 2개 행의 배열 필드만 갱신) |
| `evidence_document` | 126 (변동 없음) |
| `evidence_chunk` | 8,485 (변동 없음) |
| `evidence_chunk_ingredient` | 8,504 (변동 없음) |
| `product` | 2,262 (변동 없음) |
| `product_ingredient`(literal BHA 링크) | 8 (변동 없음 - 그대로 유지) |

### Integrity

- literal BHA row 자체: 삭제/변경 없음(id, 이름, 참조 전부 그대로)
- Salicylic Acid / Betaine Salicylate: `old_names_en`에 `{BHA}`만 추가, 나머지
  필드 불변
- FK 위반 없음(행 삭제가 없으므로 orphan 발생 여지 자체가 없음)
- v5_1을 별도 빈 DB에 재복원해 `alembic_version=9f4c2a7d8e61`, 위 counts,
  `old_names_en={BHA}` 두 값을 전부 재확인

### Dump

- 파일: `data/skincare_reference_2026-09-22_v5_1.dump` (로컬, git 미커밋 -
  v5/v4와 동일 정책)
- 크기: 80,745,448 bytes
- SHA-256: `97d97d4d48db94fb16e6f5dd18b76297f9efc4b123ea00b25fdbe93277291d4c`
  (체크섬 파일: `data/skincare_reference_2026-09-22_v5_1.dump.sha256`)
- **v5 원본은 전혀 건드리지 않았다** - 크기(80,744,958 bytes)와 SHA-256
  (`48d8ef14...`) 수정 전후 동일 재확인

## 판정

`READY_FOR_FINAL_HANDOFF: YES`

Data 범위 안에서만(`ingredient_master.old_names_en` 배열 값 추가) 최소
변경으로 literal "BHA"가 단독 canonical 후보로 확정되지 않고, 기존
계약(`ambiguous_candidates`)에 따라 모호 성분군으로 처리되게 만들었다.
Agent/Backend 코드는 한 줄도 고치지 않았고, 새 schema도 추가하지 않았다.
회귀 대상(BHA/살리실릭애씨드/베타인살리실레이트/무관 성분 5종) 전부
기대대로 동작함을 실제 production 코드 호출로 확인했다.
