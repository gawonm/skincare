# NIA Case Anchor 골든셋 검색 평가 보고서

> 평가 시각: 2026-09-24 17:09 KST
>
> 상태: **24개 Anchor 골든셋 구축 및 실제 DB A/B/C 평가 완료**
>
> 결론: 복수 질의와 전용 rerank 질의는 채택하지 않는다. 후속 구현은 충실한 단일 질의,
> Top-40 검색, 고민 메타데이터 선별, 동일 질의 rerank를 사용한다.

## 1. 평가 목적

NIA Case 문서는 같은 피부 고민과 유사한 답변을 가진 합성 사례가 다수 반복된다. 넓은 사용자
질의에 대해 일부 Case ID만 임의로 정답 처리하면 동등한 사례를 오답으로 평가하게 된다.

이번 평가는 검색 순위와 무관하게 실제 Case를 먼저 선정하고, 해당 질문을 사용자 표현으로 다시
작성한 뒤 원본 `case_id`를 정답으로 고정하는 Anchor 방식으로 구성했다. 따라서 이 평가는
전체 관련 문서를 빠짐없이 찾는 의미 검색 Recall이 아니라, 구별 가능한 사용자 조건을 가진 원본
사례를 다시 찾는 known-item retrieval 회귀 평가다.

## 2. 골든셋 구성

- 전체 24건
- 개발용 18건: 원본 `training` split
- 홀드아웃 6건: 원본 `validation` split
- 각 질의의 `relevant_case_ids`: 원본 Anchor Case ID 1개
- 검색 결과를 보기 전에 고정 seed `nia-anchor-v1`으로 카테고리별 Case를 추출했다.
- 질의에는 연령, 성별, 피부 타입, 부위, 계절·환경·생활 조건을 보존했다.
- 원본 답변에 포함된 추천 성분명은 질의에 넣지 않았다.

카테고리 분포는 모공 5건, 미백 4건, 여드름 4건, 홍조 3건, 악건성 3건, 주름 2건,
민감성 2건, 탄력 저하 1건이다.

골든셋 파일:
`tests/agent/nia_case_retrieval_golden_24.jsonl`

## 3. 재현 조건

| 항목 | 값 |
| --- | --- |
| Git HEAD | `d6e062c` |
| DB | `skincare_reference_20260923_v5_2` |
| NIA Case 수 | 3,581건 |
| text version | `nia_case_text/v1` |
| embedding | `BAAI/bge-m3`, 1,024차원 |
| reranker | `BAAI/bge-reranker-v2-m3` |
| 1차 후보 수 | Top-20 |
| 최종 후보 수 | Top-3 |

비교 실험은 다음과 같다.

| 실험 | 1차 검색 | 최종 rerank 질의 |
| --- | --- | --- |
| baseline | canonical 단일 질의 | canonical 질의 |
| multi_query | PROFILE/CONCERN/NATURAL_QUESTION + RRF | canonical 질의 |
| multi_query_rerank | PROFILE/CONCERN/NATURAL_QUESTION + RRF | 전용 상세 질의 |

Anchor가 질의당 하나이므로 이번 평가에서는 Hit@20과 Recall@20이 같은 값이다.

## 4. 평가 결과

### 4.1 전체 24건

| 실험 | Hit@20 | Recall@20 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: |
| baseline | **91.7%** | **91.7%** | **0.8125** | **0.8289** |
| multi_query | 50.0% | 50.0% | 0.4583 | 0.4692 |
| multi_query_rerank | 50.0% | 50.0% | 0.2847 | 0.3080 |

### 4.2 개발용 18건

| 실험 | Hit@20 | Recall@20 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: |
| baseline | **88.9%** | **88.9%** | **0.7500** | **0.7718** |
| multi_query | 50.0% | 50.0% | 0.4444 | 0.4590 |
| multi_query_rerank | 50.0% | 50.0% | 0.2685 | 0.2996 |

### 4.3 홀드아웃 6건

| 실험 | Hit@20 | Recall@20 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: |
| baseline | **100.0%** | **100.0%** | **1.0000** | **1.0000** |
| multi_query | 50.0% | 50.0% | 0.5000 | 0.5000 |
| multi_query_rerank | 50.0% | 50.0% | 0.3333 | 0.3333 |

## 5. 케이스별 Anchor 순위

`B-R`은 baseline 1차 순위, `M-R`은 multi-query RRF 순위다. `B-3`, `M-3`, `F-3`은 각각
baseline, multi-query+canonical rerank, multi-query+전용 rerank의 최종 Top-3 순위다.
`—`는 해당 cutoff에 Anchor가 없다는 뜻이다.

| evaluation_id | B-R | M-R | B-3 | M-3 | F-3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `dev_acne_m27_combo_cheek` | 2 | 10 | 1 | 1 | 2 |
| `dev_acne_f14_combo_cheek` | 2 | — | 1 | — | — |
| `dev_acne_m26_oily_transition` | 4 | — | 1 | — | — |
| `dev_dry_m28_transition_stress` | 7 | 7 | 2 | 2 | — |
| `dev_dry_m34_combo_multi_area` | 2 | 2 | 1 | 1 | 1 |
| `dev_pore_m38_oily_transition` | 4 | 19 | 1 | 1 | 2 |
| `dev_pore_m31_normal_cheek_nose` | 10 | — | — | — | — |
| `dev_pore_f26_combo_stress_makeup` | 2 | — | 2 | — | — |
| `dev_pore_f39_combo_elasticity` | — | — | — | — | — |
| `dev_red_f37_combo_transition` | 1 | 1 | 2 | 2 | — |
| `dev_red_f30_oily_temperature` | 1 | — | 1 | — | — |
| `dev_sag_f22_combo_nose` | 1 | — | 1 | — | — |
| `dev_sensitive_m35_temple` | 1 | 4 | 1 | 1 | 3 |
| `dev_pigment_m34_combo_stress` | — | — | — | — | — |
| `dev_pigment_f32_normal_cheek_nose` | 1 | 2 | 1 | 1 | 2 |
| `dev_pigment_m31_oily_nightwork` | 12 | — | 1 | — | — |
| `dev_wrinkle_m36_oily_sun_diet` | 1 | 1 | 1 | 1 | 1 |
| `dev_wrinkle_f34_dry_pollution` | 1 | 3 | 1 | 1 | 1 |
| `holdout_acne_f23_combo_cheek_nose` | 1 | 8 | 1 | 1 | — |
| `holdout_dry_f26_transition_hormone` | 2 | — | 1 | — | — |
| `holdout_pore_f36_combo_environment` | 1 | — | 1 | — | — |
| `holdout_red_f33_combo_chronic` | 1 | 4 | 1 | 1 | 1 |
| `holdout_sensitive_m38_dry_transition` | 1 | 18 | 1 | 1 | 1 |
| `holdout_pigment_f26_combo_pollution` | 19 | — | 1 | — | — |

## 6. 진단

### 6.1 복수 질의 후보 회수가 baseline보다 악화됐다

- baseline이 놓친 2건을 multi-query가 새로 회수한 사례는 0건이다.
- baseline이 회수한 Anchor 중 10건을 multi-query가 Top-20 밖으로 밀어냈다.
- multi-query가 회수한 12건은 canonical rerank를 적용하면 모두 Top-3 안에 들어왔다.
- 따라서 현재 가장 큰 문제는 reranker 이전의 복수 질의 후보 구성이다.

현재 RRF 입력에는 생성된 PROFILE/CONCERN/NATURAL_QUESTION 결과만 들어가고, 상세 조건을 가진
canonical 검색 결과는 별도 baseline으로만 계산된다. 생성 질의가 일반화될수록 중복 사례가 많은
코퍼스에서 Anchor가 밀려난다.

### 6.2 고민어 선택이 사용자 의도 일부를 잘못 덮어쓴다

- `dev_pigment_m31_oily_nightwork`는 사용자가 "트러블을 피하면서"라고 말한 표현 때문에
  생성 검색 질의가 미백이 아니라 `트러블 피부`에만 집중했다.
- `dev_sag_f22_combo_nose`는 처짐·탄력 저하가 주목적이지만 원문에 `모공`이 있어 생성 질의가
  `모공 피부`에만 집중했다.
- 명시 cue가 하나라도 발견되면 제공된 `skin_concerns`보다 우선되는 현재 규칙이 복합 의도에서
  주요 고민을 제거할 수 있다.

### 6.3 구별 조건이 생성 질의에서 소실된다

볼·코·관자놀이 같은 부위, 야근·스트레스·화장·미세먼지 같은 원인 조건이 canonical 질의에는
있지만 생성 검색 질의에는 대부분 남지 않는다. 유사 사례가 많은 데이터에서는 이런 조건이
Anchor를 구별하는 핵심 신호다.

또한 planner가 원문에서 추출한 나이 표현을 이미 나이가 포함된 canonical 질의 앞에 다시 붙여
`14살 14세`, `26살 26세`처럼 중복되는 사례가 확인됐다.

### 6.4 전용 rerank 질의도 현재는 악화됐다

multi-query 후보 12건은 canonical rerank에서 모두 Top-3에 들었지만 전용 rerank 질의에서는
9건만 Top-3에 남았다. 전용 질의가 후보 선택에 필요한 세부 조건을 충분히 보존하지 못해
`dev_dry_m28_transition_stress`, `dev_red_f37_combo_transition`,
`holdout_acne_f23_combo_cheek_nose`를 Top-3 밖으로 밀어냈다.

## 7. 판단과 다음 수정 기준

현재 결과로는 복수 질의 검색과 전용 rerank 질의를 품질 개선 완료로 판정할 수 없다. 운영
기본값은 baseline을 유지하는 것이 맞다.

후속 수정은 개발용 18건에서 다음 순서로 검증하고, 홀드아웃 6건은 최종 확인 전까지 튜닝에
사용하지 않는다.

1. canonical 검색 결과도 RRF contribution에 포함해 기존 회수 성능을 보존한다.
2. 원문의 명시 cue와 `skin_concerns`를 대체 관계가 아니라 병합·우선순위 규칙으로 재설계한다.
3. 부위와 환경·생활 조건 중 Case 구별에 필요한 항목을 결정적으로 보존한다.
4. canonical 질의에 이미 포함된 연령·성별 표현을 다시 앞에 붙이지 않는다.
5. 전용 rerank 질의는 canonical보다 성능이 실제로 좋아질 때만 사용한다.

## 8. 검증 결과

```text
골든셋 구조·중복 테스트: 3 passed
Ruff: All checks passed
DB ID 확인: 24/24 존재
split 불일치: 0
text/model 버전 불일치: 0
```

## 9. 후속 단일 질의·메타데이터 선별 평가

초기 복수 질의안의 회귀 원인이 부위·환경·생활 조건 소실과 과도한 일반화였으므로, 후속안은
사용자 원문에서 상품 추천과 루틴 실행 지시만 제거했다. 나이·성별·계절·부위·생활 조건과 피부
고민은 그대로 보존했다.

비교 조건은 다음과 같다.

| 실험 | 1차 검색 | reranker 입력 후보 | rerank 질의 |
| --- | --- | --- | --- |
| `baseline_top20` | 기존 canonical, Top-20 | 벡터 Top-20 | canonical |
| `single_top40` | 충실한 단일 원문, Top-40 | 벡터 Top-40 | 동일 단일 질의 |
| `single_top40_metadata` | 충실한 단일 원문, Top-40 | 고민 직접 일치 최대 20건 | 동일 단일 질의 |

모든 실험의 reranker 문서는 조건을 맞추기 위해 Case 답변·추론을 제외하고 저장 메타데이터와 원
질문만 사용했다.

| 실험 | Hit@20 | Recall@20 | Hit@40 | Recall@40 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline_top20` | 87.5% | 87.5% | 87.5% | 87.5% | 0.7083 | 0.7302 |
| `single_top40` | **91.7%** | **91.7%** | **91.7%** | **91.7%** | 0.8264 | 0.8388 |
| `single_top40_metadata` | **91.7%** | **91.7%** | **91.7%** | **91.7%** | **0.8403** | **0.8596** |

해석 시 다음 한계를 함께 본다.

- 이 골든셋은 질의당 Anchor ID 하나인 known-item 평가다. 의미상 동등한 다른 Case를 오답으로
  처리하므로 실제 사용자 적합성을 완전히 대변하지 않는다.
- 이번 24건에서는 Top-20 밖, Top-40 안에서 새로 회수된 Anchor가 없었다. 따라서 후보 수 40의
  직접적인 Anchor recall 이득은 확인되지 않았다.
- 메타데이터 선별은 Hit/Recall을 높이지 않았지만, 최종 MRR@3과 nDCG@3을 소폭 개선했다.
- 실제 건조·민감 예시에서는 고민 일치 후보가 Top-20 3건에서 Top-40 6건으로 늘어, 최대 20건만
  rerank하는 구조에서 후보 다양성 확보 효과는 확인했다.

따라서 Top-40은 검색 정확도를 보장하는 숫자가 아니라, 한 번의 DB 검색으로 고민 일치 후보를
충분히 확보하기 위한 운영 상한으로 사용한다. 지연 시간이 문제가 되면 같은 평가기로 Top-30과
Top-40을 다시 비교한 뒤 낮출 수 있다.
