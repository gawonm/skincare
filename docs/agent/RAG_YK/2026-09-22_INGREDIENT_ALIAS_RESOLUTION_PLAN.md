# 성분 식별 정규화 및 확정 별칭 조회 계획

> 작성일: 2026-09-22
>
> 상태: **계약 초안 / 코드 미구현**
>
> 관련 계약: [`backend-to-agent.md` 9.4절](../../contracts/backend-to-agent.md#94-ingredient와-product-조회)

## 1. 문제

NIA Case Top-3에서 선별된 성분명을 `IngredientRepository.resolve()`로 조회할 때 다음 결과가
관찰됐다.

```text
알로에 베라 잎즙 파우더 → no_results
고추냉이 뿌리 추출물 → no_results
미네랄 솔트 → no_results
안디로바 씨 오일 → no_results
카라파 구아이아넨시스 씨드 오일 → no_results
키틴 → 키틴 / c4399298-58ae-4df1-8f6b-eeaae7a98ce3
```

`ingredient_master`에는 대상 행이 존재하지만, 현재 Backend 조회는 정규화 컬럼에도 정규화하지
않은 요청 문자열을 비교한다. 따라서 공백 차이만 있어도 `NO_RESULTS`가 된다. 또한 Agent의 확정
별칭 목록에는 `파우더 → 가루` 표기와 학명 기반 한글 표기가 등록돼 있지 않다.

동일 성분이 로그에 여러 번 나타나는 것은 여러 Case에서 같은 성분을 선별한 결과다. 이 계획은
성분명당 표준 ID를 정확히 확정하는 범위만 다루며, trace 표시 중복이나 조회 캐시는 별도 과제로
남긴다.

## 2. 실제 마스터 확인 결과

2026-09-22 현재 `config.yaml`이 가리키는 `ingredient_master`를 읽기 전용으로 조회해 다음 행을
확인했다.

| 입력 표현 | 표준 국문명 | 표준 영문명 | `ingredient_id` | 처리 방식 |
| --- | --- | --- | --- | --- |
| 알로에 베라 잎즙 파우더 | 알로에베라잎즙가루 | Aloe Barbadensis Leaf Juice Powder | `7989ceef-b0d9-49a9-9791-c25cde0cb730` | Agent 확정 별칭 |
| 고추냉이 뿌리 추출물 | 고추냉이뿌리추출물 | Wasabia Japonica Root Extract | `7edf9862-697b-404b-8d85-c76fd4adef44` | Backend 공백 정규화 |
| 미네랄 솔트 | 미네랄솔트 | Mineral Salts | `8c3a04b5-9741-4cb4-b1d4-5260b3e25382` | Backend 공백 정규화 |
| 안디로바 씨 오일 | 안디로바씨오일 | Carapa Guianensis Seed Oil | `c165de49-0f65-40cf-b6b6-3c1c709b8aa2` | Backend 공백 정규화 |
| 카라파 구아이아넨시스 씨드 오일 | 안디로바씨오일 | Carapa Guianensis Seed Oil | `c165de49-0f65-40cf-b6b6-3c1c709b8aa2` | Agent 확정 별칭 |
| 키틴 | 키틴 | Chitin | `c4399298-58ae-4df1-8f6b-eeaae7a98ce3` | 현행 정확 일치 유지 |

표의 UUID는 별칭 코드에 하드코딩하지 않는다. Agent는 검증된 표준 국문명으로 재조회하고,
최종 UUID는 항상 Backend가 현재 DB에서 반환한다. 마스터 재적재로 UUID가 바뀌어도 별칭 코드가
오래된 ID를 반환하지 않게 하기 위해서다.

## 3. 책임 분리

```text
NIA Case raw_name
  → Backend 원문 조회
  → NO_RESULTS일 때만 Agent 확정 별칭 변환
  → Backend 표준명 재조회
  → IngredientResolveResult
```

### 3.1 Backend: 표기 정규화 정확 일치

수정 대상은 `backend/repositories/agent_ingredient_repository.py`다.

- 국문 요청 키는 앞뒤 공백을 제거하고 모든 공백 문자를 제거한다.
- 영문 요청 키는 소문자화한 뒤 공백·하이픈·괄호를 제거한다.
- `language` 기본값만 보고 한쪽을 생략하지 않고, 같은 `name`에서 두 키를 모두 계산한다.
- 국문 키는 `normalized_name_ko`, 영문 키는 `normalized_name_en`과 비교한다.
- 구 국문명·구 영문명 배열도 같은 규칙으로 정규화한 값이 정확히 일치할 때만 후보로 인정한다.
- 표준명 원문 정확 일치 경로는 호환성을 위해 유지한다.
- 부분 일치, 유사도 검색, 형태소 추정은 추가하지 않는다.

정규화는 요청 파라미터에 먼저 적용하고 기존 scalar 정규화 컬럼과 직접 비교한다. 모든 행의
컬럼에 `replace()`를 적용하는 방식은 향후 인덱스를 사용하기 어렵게 하므로 기본 구현으로 삼지
않는다. 배열형 구명칭은 정규화 전용 컬럼이 없으므로 `unnest()` 내부에서만 동일 규칙을 적용한다.

### 3.2 Agent: 검증된 확정 별칭

수정 대상은 `agent/rag/retrieval/ingredient_alias_mapper.py`다.

다음 두 동의어만 `IngredientAliasKind.EXACT_EQUIVALENT`로 추가한다.

| 소비자·Case 표현 | Backend에 재조회할 표준 국문명 |
| --- | --- |
| 알로에 베라 잎즙 파우더 | 알로에베라잎즙가루 |
| 카라파 구아이아넨시스 씨드 오일 | 안디로바씨오일 |

Agent 별칭 키는 기존처럼 NFKC·대소문자·공백을 정규화한다. 그러므로 같은 단어의 공백 유무를
각각 등록하지 않는다. `Aloe Barbadensis Leaf Juice Powder`, `Carapa Guianensis Seed Oil`은
Backend 영문 정규화 정확 일치로 처리되므로 Agent 별칭에 중복 등록하지 않는다.

## 4. 안전 경계

다음 규칙은 도입하지 않는다.

- 모든 `파우더`를 `가루`로 바꾸는 전역 치환
- 모든 `씨드 오일`을 `씨오일`로 바꾸는 전역 치환
- 부분 문자열이 비슷하다는 이유만으로 하나의 표준 성분을 선택하는 fuzzy matching
- Agent 코드에 `ingredient_id` UUID를 직접 고정하는 매핑
- `NO_RESULTS`가 아닌 DB 오류나 모호한 후보를 별칭 조회로 덮어쓰기

전역 치환은 유도체·발효물·혼합물 이름 일부까지 바꿔 다른 성분으로 연결할 수 있다. 별칭은 실제
마스터의 표준 영문명과 UUID로 일대일 관계가 확인된 전체 이름에만 추가한다.

## 5. 상태와 실패 계약

- 정확히 한 행: `SUCCESS`와 `ingredient`
- 서로 다른 표준 성분이 둘 이상: `SUCCESS`와 `ambiguous_candidates`; Agent가 임의 선택하지 않음
- 원문 조회와 확정 별칭 재조회 모두 무결과: `NO_RESULTS`
- DB·SQL·DTO 변환 실패: 원인을 포함한 `ERROR`; 별칭 fallback으로 숨기지 않음
- Agent 별칭 재조회는 원문 조회가 `NO_RESULTS`일 때만 실행
- 재조회 결과의 canonical 이름·aliases가 요청한 확정 대상과 일치하지 않으면 `NO_RESULTS`

공개 Pydantic 타입과 메서드 시그니처는 변경하지 않는다.

## 6. 구현 순서

1. `docs/contracts/backend-to-agent.md` 9.4절 합의
2. Backend 요청 정규화 및 Repository SQL 테스트
3. Agent 확정 별칭과 fallback 테스트
4. 실제 DB에서 표의 6개 입력을 조회하는 통합 회귀 테스트
5. 전체 Ruff·pytest 및 Trace CLI 확인

Agent와 Backend 코드는 계약 확인 전에는 수정하지 않는다.

## 7. 완료 기준

- 표의 앞선 5개 `NO_RESULTS` 입력이 각각 명시된 표준명과 UUID 하나로 해소된다.
- `키틴`의 기존 UUID가 유지된다.
- 공백이 없는 기존 표준명과 영문 표준명 조회가 깨지지 않는다.
- 모호한 성분군과 DB 오류는 단일 UUID로 축소되지 않는다.
- 새 모델·마이그레이션·설정 키·라이브러리가 추가되지 않는다.
- 같은 성분이 여러 Case에서 추출돼도 최종 `ingredient_ids`는 기존 정책대로 중복 제거된다.

## 8. 구현 비범위

- `ingredient_master` 데이터 수정 또는 구명칭 배열 보강
- `models/`, `migrations/`, ERD 변경
- 전체 성분명의 자동 번역·음역 사전 생성
- fuzzy search, trigram, 별도 검색 인덱스
- Case별 반복 trace 표시 제거 또는 Repository 조회 캐시

## 9. 2026-09-23 Case 성분 별칭 보완

실제 Trace와 현재 `ingredient_master`를 대조해 다음 확정 동의어를 추가했다. UUID는 별칭 코드에
넣지 않고 표준 국문명으로 Backend를 다시 조회한다.

| Case 표현 | 재조회 표준 국문명 | 판단 |
| --- | --- | --- |
| `알로에신`, `Aloesin` | `알로에신` | 동일 성분의 국문·영문 표기 |
| `헥사펩타이드-2`, `Hexapeptide-2` | `헥사펩타이드-2` | 동일 성분의 국문·영문 표기 |
| `서양 고추냉이 뿌리 추출물`, `Cochlearia Armoracia Root Extract` | `호스래디시뿌리추출물` | 서양고추냉이 표준 성분 |

`Cochlearia Armoracia`는 `Wasabia Japonica`의 `고추냉이뿌리추출물`과 서로 다른 마스터
성분이다. 기존 별칭의 잘못된 연결을 `호스래디시뿌리추출물`로 바로잡았다.

Trace CLI도 Claim 원문 검증에서 제외돼 성분 조회가 실행되지 않은 경우를
`ingredient_id 미확정`으로 표시하지 않고 `조회 미실행`으로 구분한다.
