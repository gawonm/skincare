# Agent 성분 별칭 및 원자적 Case Claim 보강

- 기록 일시: 2026-09-21 14:59 (KST)
- 대상 브랜치: `integration/nia-case-rag`
- 범위: `agent/`, `tests/agent/`, Agent 문서
- Backend·Data·DB 변경: 없음

## 1. 변경 배경

최신 통합 DB를 사용한 다음 질의에서 NIA Case 검색과 Claim 추출은 수행됐지만 상품 후보가 생성되지 않았다.

```text
피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?
```

DB에는 나이아신아마이드 및 살리실릭애씨드와 연결된 confirmed 상품이 존재한다. 실패 원인은 상품 데이터 부족이 아니라 다음 두 경계였다.

1. NIA 원문의 `살리실산(BHA)`, `티트리 오일`이 DB 표준 성분명과 일치하지 않았다.
2. 독립적으로 설명된 여러 성분이 하나의 `combination_effect`로 묶이면, 일부 성분의 매칭 실패로 정상 매칭 성분까지 Evidence/Product 단계에서 제외될 수 있었다.

## 2. 성분 별칭 정책

별칭 데이터는 Agent에서 관리한다. Backend Repository와 Data의 기존 `IngredientNameMatcher`는 수정하지 않는다.

별칭은 다음 두 종류로 분리했다.

### 2.1 확정 동의어

단일 표준 성분으로 안전하게 연결할 수 있는 표현이다.

| 소비자 표현 | 표준 성분명 |
| --- | --- |
| 살리실산 | 살리실릭애씨드 |
| 살리실산(BHA) | 살리실릭애씨드 |
| Salicylic Acid | 살리실릭애씨드 |
| 비타민 C·Ascorbic Acid·아스코르빈산 | 아스코빅애씨드 |

Repository의 원문 exact 조회가 실패했을 때만 확정 동의어로 한 번 재조회한다. 원문 조회가 성공한 경우에는 별칭이 결과를 덮어쓰지 않는다.

### 2.2 모호한 성분군

하나의 표준 ID로 축소하면 잘못된 성분을 선택할 수 있는 표현이다.

| 소비자 표현 | 후보 예시 | 처리 |
| --- | --- | --- |
| BHA | 살리실릭애씨드, 베타인살리실레이트 | `AMBIGUOUS` 유지 |
| 티트리 오일 | 티트리잎오일, 티트리꽃/잎/줄기오일 | `AMBIGUOUS` 유지 |

모호한 성분군은 단일 성분 ID로 자동 승격하지 않는다. Case Claim에서는 해당 성분만 보류하며 다른 독립 Claim의 성분 해석을 막지 않는다.

## 3. Case Claim 원자성 및 조합 방어

`ingredient_effect`는 성분을 정확히 하나만 가진다. 독립적으로 나열된 여러 성분은 각각 별도 Claim으로 추출하도록 프롬프트를 보강했다.

```text
첫째 살리실산은 각질을 정리한다.
둘째 나이아신아마이드는 피지를 조절한다.
```

위 문장은 다음 두 Claim이어야 한다.

```text
ingredient_effect(살리실산)
ingredient_effect(나이아신아마이드)
```

`combination_effect`에는 `combination_relation_quote`를 추가했다. 이 값은 Case 원문에 실제로 존재하면서 `함께`, `병용`, `조합`, `동시에`, `혼합`, `시너지`와 같은 공동 관계를 명시해야 한다.

```text
살리실산과 나이아신아마이드를 함께 사용하면 피지 관리에 도움을 준다.
```

위와 같은 명시적 조합만 조합 Claim 검증을 통과한다. `첫째`, `둘째`, `또한`처럼 독립 효능을 나열한 문장은 조합 Claim으로 통과하지 못한다.

조합 Claim의 모든 성분이 해결되지 않으면 Evidence anchor를 만들지 않는 기존 방어 규칙은 유지한다. 개별 Evidence만으로 조합 효능 전체가 지원됐다고 판단하지 않기 위해서다.

## 4. Prompt 및 DTO 버전

- Case Claim prompt version: `nia-case-claim/v2`
- 신규 필드: `ExtractedCaseClaim.combination_relation_quote`
- 신규 검증 사유:
  - `combination_relation_not_found`
  - `combination_relation_not_explicit`

LLM은 성분 ID, Evidence 상태, Citation 또는 상품 추천 가능 여부를 계속 결정하지 않는다.

## 5. 변경 파일

- `agent/rag/retrieval/ingredient_alias_mapper.py`
  - 확정 동의어와 모호한 성분군 분리
  - 살리실산 및 티트리/BHA 정책 추가
- `agent/nodes.py`
  - 명시 성분 해석에서 모호한 성분군을 단일 ID로 승격하지 않음
- `agent/rag_workflow.py`
  - Case Claim 성분 해석에 동일한 모호성 정책 적용
- `agent/rag/case_claim_schemas.py`
  - 조합 관계 인용 필드 및 검증 사유 추가
- `agent/rag/case_claim_validator.py`
  - 조합 관계 exact quote와 명시적 공동 표현 검증
- `agent/prompts.py`
  - 독립 Claim 분리 예시와 조합 Claim 작성 규칙 추가
- `tests/agent/test_entity_resolution_fallback.py`
- `tests/agent/test_case_runtime_claim_processing.py`

## 6. 검증 결과

관련 테스트만 실행했다.

```text
별칭·Claim DTO·검증 테스트: 53 passed
Case → Claim → Evidence/Product 연결 테스트: 6 passed
Ruff passed
```

동일 질의 1건만 최신 통합 DB와 실제 OpenAI 경로로 재실행했다.

```text
피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?
```

확인 결과:

- DB: `skincare_integrated_20260920`
- `살리실산(BHA)`와 `나이아신아마이드`가 서로 다른 `ingredient_effect` Claim으로 출력됨
- `살리실산(BHA)`는 표준 성분 미확정 목록에서 제외됨
- `BHA` 단독 표현은 모호한 성분군으로 유지됨
- 이전 실행과 달리 Claim 기반 상품 후보 10건이 생성됨
- Evidence Citation은 0건이며 Evidence 정책은 기존 보류 상태를 유지함
- 별도 도구 실패 2건이 남아 있음. compact 출력만으로 실패 포트를 확정할 수 없어 이번 범위에서 원인을 추정하거나 숨기지 않음

## 7. 남은 사항

- Agent 별칭 카탈로그를 추가할 때 확정 동의어와 성분군을 반드시 구분한다.
- AHA, 레티노이드, 세라마이드, 히알루론산 등은 아직 자동 매핑하지 않는다.
- `티트리 오일`은 단일 `티트리잎오일`로 강제 매핑하지 않는다.
- E2E의 도구 실패 2건: verbose 실행을 통해 살리실산 식약처 근거의 `section=NULL` 역직렬화 실패로 규명되었으며, Antigravity에 의해 수정 및 검증 완료됨 (참조: `2026-09-21_1530_EVIDENCE_NULLABLE_SECTION_FIX.md`)
- Evidence 저장·검수 상태 문제는 별도 보류 문서에 따라 이후 작업으로 유지한다.
