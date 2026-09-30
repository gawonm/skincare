# 상품 카테고리 → 루틴 역할 감사

> - generated_at: 2026-09-30
> - commit / branch: `ea915de` (origin/main) / `docs/data-runtime-quality-audits-v2`
> - DB: `skincare_reference_20260923_v5_2` (로컬 Docker, SELECT 전용) — Alembic `cdff29b164d8`
> - DB 이름과 핸드오프 기준 dump 이름이 대응하지만 dump 바이트 일치는 확인하지 않아 SHA256은 적지 않는다.
> - 핵심 행 수: `product` 2,262 (confirmed 성분 ≥1: 2,180)
> - 수치 원본: [product_routine_role_distribution.csv](product_routine_role_distribution.csv),
>   [product_routine_role_ambiguous_samples.csv](product_routine_role_ambiguous_samples.csv)
> - 방법: 운영과 같은 방식(`COALESCE(service_category, product_type_normalized, category1)`)으로 `ProductRecord`를
>   만들어 실제 `RoutineProductSelector.role()`을 호출했다. LLM 실행 없음, DB 쓰기 없음.

## 결론

- 새 ontology나 `routine_role` 컬럼 없이 현재 selector가 **75.7%(1,712개)를 역할로 분류**한다.
  나머지 550개(24.3%)는 `unclassified`다.
- `unclassified` 원인은 셋이다: 카테고리가 역할 어휘에 없음(369), `service_category`가 NULL이라
  `category1`의 출처 이름으로 떨어짐(154), 특수 용도명 강등(27).
- selector는 `special_care` 역할을 내지 않는다(0건).

## 역할 분포 (전체 2,262)

| selector 역할 | 전체 | confirmed ≥1 |
| --- | ---: | ---: |
| care | 729 | 717 |
| unclassified | 550 | 496 |
| cleanse | 549 | 538 |
| moisturize | 434 | 429 |
| special_care | 0 | 0 |

## 카테고리별 결과

| 해석된 category | 상품 | selector 역할 |
| --- | ---: | --- |
| 클렌저 | 549 | cleanse |
| 에센스·세럼 | 355 | care |
| 토너·패드 | 194 | care |
| 앰플 | 180 | care |
| 크림·로션 | 434 | moisturize |
| 크림·로션 | 27 | unclassified (이름에 아이크림·마스크·팩 등) |
| 기타 | 203 | unclassified |
| 마스크·패치 | 159 | unclassified |
| OliveYoungGlobal (service_category NULL) | 154 | unclassified |
| 선케어 | 7 | unclassified |

## 모호한 경우

| 사유 | 개수 | confirmed ≥1 |
| --- | ---: | ---: |
| UNMAPPED_CATEGORY (기타 203, 마스크·패치 159, 선케어 7) | 369 | 328 |
| SERVICE_CATEGORY_NULL_FALLBACK | 154 | 141 |
| NAME_DOWNGRADE (크림·로션 → 특수 용도명) | 27 | 27 |

- **NULL 154개**: `service_category`와 `product_type_normalized`가 모두 비어 `category1` 값 `OliveYoungGlobal`이
  카테고리로 쓰인다. 카테고리가 아니라 수집 출처 이름이다. 운영 fallback 식
  `COALESCE(service_category, product_type_normalized, category1)`을 그대로 적용한 결과이며, 154개 모두
  `product_type_normalized`가 NULL이고 `category1`이 `OliveYoungGlobal`이다.
- 이것은 **데이터 손상이 아니라 현재 fallback·카테고리 커버리지 문제**다. 결과는 `unclassified` 방향(보수적)이며,
  runtime 수정은 Agent/Backend FOLLOW-UP이다.
- 기타·마스크·선케어는 selector가 역할을 주지 않는 범주다. 선케어는 아침 루틴 필수 단계인데 역할이 없다.
- 샘플은 사유·카테고리별로 `source_product_id` 순 10건까지 CSV에 저장했다(47행).

## Q05 샘플 상품 확인

| 상품 | 카테고리 | 역할 | confirmed 성분 |
| --- | --- | --- | ---: |
| 숨37 Nuruk Daily Exfoliating 클렌저 | 클렌저 | cleanse | 138 |
| 아누아 레티놀 0.1 카페인 아이크림 | 크림·로션 | unclassified (이름 강등) | 75 |
| 이소이 포 맨 아쿠아 수딩 토너 | 토너·패드 | care | 22 |
| 썸바이미 Bye Bye 블랙 버블 클렌저 | 클렌저 | cleanse | 49 |

아이크림이 `moisturize`가 아닌 `unclassified`인 것은 의도된 강등이다.

## 남은 위험

- confirmed 성분 0개인 82개 상품은 역할이 있어도 추천 후보에 나오지 않는다(cleanse 11 / care 12 / moisturize 5 /
  unclassified 54).
- `unclassified` 상품은 selector가 루틴 입력으로 **1개만** 넘긴다. 마스크·패치가 159개여도 대표 1개만 쓰인다.

## FOLLOW-UP (수정하지 않음)

- `service_category` NULL 154건의 `category1` 대체 경로 정리 (Data: 분류 backfill / Backend: COALESCE 쿼리).
- 선케어·마스크·패치를 루틴에서 어떻게 다룰지 정책 (Agent 결정).
