# 상품–성분 매핑 무결성 감사

> - generated_at: 2026-09-30
> - commit / branch: `ea915de` (origin/main) / `docs/data-runtime-quality-audits-v2`
> - DB: `skincare_reference_20260923_v5_2` (로컬 Docker, SELECT 전용) — Alembic `cdff29b164d8`
> - DB 이름과 핸드오프 기준 dump 이름이 대응하지만 dump 바이트 일치는 확인하지 않아 SHA256은 적지 않는다.
> - 핵심 행 수: `product` 2,262 / `product_ingredient_snapshot` 2,216 / `product_ingredient` 84,390
> - 수치 원본: `product_ingredient_integrity_metrics.csv` (로컬 생성물, git 미추적)

## 결론

- 구조 무결성은 깨끗하다. confirmed는 전부 `ingredient_id`가 있고, 비confirmed는 전부 없으며, 존재하지 않는
  성분을 가리키는 행이 0건이다.
- 품질 위험은 **매칭 커버리지**에 있다. 토큰의 7.2%(6,110건)가 confirmed가 아니고, 그중 `Water`와
  `Fragrance` 두 이름이 2,457건(40.2%)을 차지한다.
- 82개 상품(3.6%)은 confirmed 성분이 0개라 Agent 추천 후보에서 빠진다
  (`TwoLayerProductRepository`는 confirmed 연결 상품만 노출).

## 매핑 상태

| 항목 | 값 | 비율 |
| --- | ---: | ---: |
| 전체 토큰 | 84,390 | 100% |
| confirmed | 78,280 | 92.76% |
| needs_review | 2,693 | 3.19% |
| unmatched | 3,417 | 4.05% |
| `token_parse_status=needs_review` | 51 | 0.06% |

매칭 방법별: `standard_name_en_normalized` 78,214 / `old_name_en_normalized` 66 (모두 confirmed),
`annotation_stripped_en_normalized` 115, `manual_review` 5,944 (모두 비confirmed), 방법 없음 51.

## 상품·스냅샷 연결

| 항목 | 값 |
| --- | ---: |
| product | 2,262 |
| snapshot | 2,216 |
| snapshot 없는 product | 46 |
| product 없는 snapshot | 0 |
| confirmed 성분 ≥1인 상품 | 2,180 |
| confirmed 성분 0개 상품 | 82 |

연결은 FK가 아니라 `(source, source_product_id)` 값이다([README](README.md) 설계 판단). 고아 snapshot이 없으므로
현재 값 연결은 일관된다.

## 무결성 점검

| 점검 | 결과 |
| --- | ---: |
| confirmed인데 `ingredient_id` NULL | 0 |
| 비confirmed인데 `ingredient_id` 있음 | 0 |
| `ingredient_master`에 없는 `ingredient_id` | 0 |
| 같은 snapshot·section의 `token_order` 중복 | 0 |
| 토큰이 하나도 없는 snapshot | 0 |
| `raw_text_hash` 중복 해시 / 초과 snapshot | 67 / 80 |

`raw_text_hash` 중복 80건은 서로 다른 상품이 같은 전성분 원문을 쓴 경우(용량 옵션·에디션 등)로 추정되며, 이번
감사에서 상품 쌍을 개별 검증하지는 않았다.

## 상위 실패 이름

| 상태 | matching_name | 건수 | 원인 |
| --- | --- | ---: | --- |
| needs_review | Water | 1,933 | 후보 4개가 동시에 걸려 자동 확정하지 못함 (`manual_review`) |
| unmatched | Fragrance | 524 | 표준 성분 후보 없음 |

`Water`는 전체 needs_review의 71.8%다. 후보 4개 중 하나를 고르는 규칙은 Data 파트 결정이므로 여기서는
제안하지 않는다.

## 핵심 활성 성분(retinol·salicylic·glycolic) 토큰

측정 정의 (재현 가능):

- 대상 테이블: `product_ingredient`, 단위는 토큰 행이다.
- 조건: `raw_token ~* '(retinol|salicylic|glycolic)'` (PostgreSQL 대소문자 무시 정규식, 부분 문자열 일치)
- DISTINCT 없음. 같은 성분이 여러 상품에 있으면 그만큼 센다. 총 477행이 379개 snapshot에 걸쳐 있다.
- confirmed 판정: `match_acceptance = 'confirmed'`. 나머지(needs_review, unmatched)는 비confirmed.
- `matching_name`으로 조건을 바꿔도 같은 값(460 / 17)이 나온다.

| 상태 | 건수 |
| --- | ---: |
| confirmed | 460 |
| 비confirmed (needs_review 6 + unmatched 11) | 17 |

- EXPECTED: 이전 탐색 측정값 522 / 20
- ACTUAL: 현재 재현 가능한 측정값 460 / 17
- REASON: 이전 집계·쿼리 정의를 저장소, 기존 문서, 로컬 로그에서 찾지 못했다. 이 보고서는 위에 명시한
  쿼리 정의를 기준으로 하며, 이전 값에 맞추지 않았다.

다른 지표(84,390, 78,280, 2,693, 3,417, 2,262, 2,216, 2,180, 1,933, 524, 80)는 모두 기준과 일치했다.

비confirmed 17건은 `Retinol (500IU/g)`처럼 함량 표기가 붙은 `needs_review`(6건)와, `Retinol*`·줄바꿈 없이 붙은
긴 전성분 문자열처럼 파싱이 덜 된 `unmatched`(11건)다. `Capryloyl Salicylic Acid`는 살리실산과 다른 성분인데
패턴에 걸려 confirmed 460건에 섞여 있다. 활성 성분 통계는 이름 부분 일치가 아니라 `ingredient_id`로 센다.

## FOLLOW-UP (수정하지 않음)

- `Water` needs_review 1,933건 해소 규칙 (Data 파트 결정).
- 파싱이 덜 된 긴 토큰은 성분 파서 개선 후보.
- snapshot 없는 상품 46개의 수집 누락 여부.
