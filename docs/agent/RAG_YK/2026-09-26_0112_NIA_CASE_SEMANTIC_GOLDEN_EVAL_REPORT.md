# NIA Case RAG Semantic Golden 평가 보고서

## 평가 범위

- 동결 사용자 질의 40개(핵심 30개, 희소 스트레스 10개)
- BGE-M3 cached dense Top-40 → 고민 메타데이터 Top-20 → bge-reranker-v2-m3 Top-3
- 최초 anchor 600건과 실제 Top-3 보완 81건, 총 681 graded qrels
- 미판정 문서를 비관련으로 간주하지 않는 pooled-anchor 평가

## 종합 결과

| 구간 | 질의 | Dense Relevant Success@40 | Dense Ceiling Hit@40 | Pooled Recall@40 | Judged Precision@40 | Metadata Relevant Retention@20 | Metadata Ceiling Hit@20 | nDCG@3 | Precision@3 | Highly Relevant Success@3 | Ceiling Hit@3 | 충돌 노출 | Top-3 정확 중복 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 90.0% | 90.0% | 57.2% | 66.3% | 94.4% | 82.5% | 0.702 | 70.0% | 52.5% | 75.0% | 15 | 3 |
| core | 30 | 90.0% | 86.7% | 59.7% | 64.7% | 95.2% | 76.7% | 0.665 | 65.6% | 46.7% | 70.0% | 13 | 3 |
| rare_stress | 10 | 90.0% | 100.0% | 49.8% | 71.0% | 92.1% | 100.0% | 0.810 | 83.3% | 70.0% | 90.0% | 2 | 0 |

## 질의별 결과

| evaluation_id | cohort | ceiling | qrels | relevant | dense recall | metadata retention | Top-3 grades | nDCG@3 | ceiling hit | conflicts |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |
| evaluation_core_pores_01 | core | 3 | 18 | 13 | 61.5% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_core_pores_02 | core | 3 | 16 | 9 | 55.6% | 100.0% | 3,0,2 | 0.570 | yes | 1 |
| evaluation_core_pores_03 | core | 3 | 17 | 14 | 28.6% | 100.0% | 0,2,2 | 0.227 | no | 1 |
| evaluation_core_pores_04 | core | 3 | 18 | 8 | 87.5% | 85.7% | 2,2,2 | 0.495 | no | 0 |
| evaluation_core_pores_05 | core | 3 | 17 | 14 | 50.0% | 71.4% | 2,2,2 | 0.429 | no | 0 |
| evaluation_core_pores_06 | core | 3 | 17 | 8 | 37.5% | 100.0% | 2,2,0 | 0.471 | no | 1 |
| evaluation_core_pores_07 | core | 3 | 18 | 11 | 18.2% | 100.0% | 3,1,1 | 0.545 | yes | 0 |
| evaluation_core_pores_08 | core | 0 | 17 | 0 | 100.0% | 100.0% | 0,0,0 | 1.000 | yes | 3 |
| evaluation_core_pigment_01 | core | 3 | 16 | 7 | 0.0% | 100.0% | 1,1,1 | 0.165 | no | 0 |
| evaluation_core_pigment_02 | core | 3 | 16 | 12 | 50.0% | 100.0% | 2,3,3 | 0.732 | yes | 0 |
| evaluation_core_pigment_03 | core | 3 | 17 | 17 | 41.2% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_core_pigment_04 | core | 2 | 18 | 1 | 100.0% | 0.0% | 0,0,0 | 0.000 | no | 3 |
| evaluation_core_pigment_05 | core | 2 | 17 | 4 | 100.0% | 100.0% | 1,2,1 | 0.531 | yes | 0 |
| evaluation_core_pigment_06 | core | 3 | 18 | 18 | 44.4% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_core_pigment_07 | core | 2 | 16 | 5 | 80.0% | 100.0% | 1,2,2 | 0.687 | yes | 0 |
| evaluation_core_pigment_08 | core | 3 | 17 | 5 | 40.0% | 100.0% | 2,3,1 | 0.531 | yes | 0 |
| evaluation_core_acne_01 | core | 3 | 17 | 10 | 70.0% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_core_acne_02 | core | 3 | 18 | 12 | 66.7% | 100.0% | 2,3,3 | 0.732 | yes | 0 |
| evaluation_core_acne_03 | core | 2 | 16 | 7 | 42.9% | 100.0% | 2,2,2 | 1.000 | yes | 0 |
| evaluation_core_acne_04 | core | 3 | 18 | 8 | 50.0% | 100.0% | 3,1,2 | 0.707 | yes | 0 |
| evaluation_core_acne_05 | core | 3 | 17 | 13 | 53.8% | 100.0% | 3,2,2 | 0.697 | yes | 0 |
| evaluation_core_acne_06 | core | 2 | 17 | 7 | 100.0% | 100.0% | 2,2,2 | 1.000 | yes | 0 |
| evaluation_core_acne_07 | core | 2 | 17 | 6 | 66.7% | 100.0% | 1,1,1 | 0.333 | no | 0 |
| evaluation_core_acne_08 | core | 3 | 18 | 8 | 87.5% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_core_composite_01 | core | 3 | 17 | 12 | 33.3% | 100.0% | 2,2,0 | 0.328 | no | 1 |
| evaluation_core_composite_02 | core | 2 | 17 | 3 | 66.7% | 100.0% | 1,1,1 | 0.333 | no | 0 |
| evaluation_core_composite_03 | core | 0 | 17 | 0 | 100.0% | 100.0% | 0,0,0 | 1.000 | yes | 3 |
| evaluation_core_composite_04 | core | 3 | 16 | 15 | 40.0% | 100.0% | 3,2,2 | 0.805 | yes | 0 |
| evaluation_core_composite_05 | core | 2 | 16 | 4 | 75.0% | 100.0% | 2,1,1 | 0.646 | yes | 0 |
| evaluation_core_composite_06 | core | 3 | 16 | 14 | 42.9% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_rare_dry_01 | rare_stress | 3 | 18 | 13 | 38.5% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_rare_dry_02 | rare_stress | 3 | 16 | 13 | 30.8% | 100.0% | 2,2,3 | 0.650 | yes | 0 |
| evaluation_rare_dry_03 | rare_stress | 3 | 17 | 13 | 30.8% | 100.0% | 2,3,3 | 0.845 | yes | 0 |
| evaluation_rare_redness_01 | rare_stress | 3 | 18 | 18 | 44.4% | 87.5% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_rare_redness_02 | rare_stress | 3 | 17 | 17 | 41.2% | 100.0% | 3,3,3 | 1.000 | yes | 0 |
| evaluation_rare_redness_03 | rare_stress | 2 | 18 | 12 | 58.3% | 100.0% | 2,2,2 | 1.000 | yes | 0 |
| evaluation_rare_wrinkles_01 | rare_stress | 3 | 16 | 12 | 50.0% | 100.0% | 2,3,3 | 0.845 | yes | 0 |
| evaluation_rare_wrinkles_02 | rare_stress | 3 | 18 | 8 | 50.0% | 100.0% | 2,1,2 | 0.397 | no | 0 |
| evaluation_rare_sensitive_01 | rare_stress | 3 | 17 | 11 | 54.5% | 33.3% | 3,2,0 | 0.596 | yes | 1 |
| evaluation_rare_sagging_01 | rare_stress | 1 | 16 | 0 | 100.0% | 100.0% | 1,1,0 | 0.765 | yes | 1 |

## 현재 설정에 대한 판정

- 핵심셋 Dense Relevant Success@40은 90.0%로 초기 90% 목표에 도달했다.
- 핵심셋 metadata relevant retention은 95.2%다. 다만 이는 최고 등급 후보 보존율과 동일한 지표가 아니므로 95% 목표와 직접 등치하지 않는다.
- 핵심셋 nDCG@3은 0.665로 초기 0.75 목표보다 낮다.
- 핵심셋 Highly Relevant Success@3은 46.7%로 초기 80% 목표보다 낮다.
- Top-3 추천 충돌 문서는 전체 15건으로, 0건 목표를 충족하지 못했다.
- 현재 병목은 Top-40 후보 수보다, 현재 증상과 반대되는 활성 성분 권고를 Top-3에서 내리지 못하는 재정렬 단계다.

### 우선 검토 질의

- Top-3 충돌 노출: evaluation_core_pores_02, evaluation_core_pores_03, evaluation_core_pores_06, evaluation_core_pores_08, evaluation_core_pigment_04, evaluation_core_composite_01, evaluation_core_composite_03, evaluation_rare_sensitive_01, evaluation_rare_sagging_01
- Dense Top-40 내 2점 이상 anchor 없음: evaluation_core_pores_08, evaluation_core_pigment_01, evaluation_core_composite_03, evaluation_rare_sagging_01
- nDCG@3 최저 5건: evaluation_core_pigment_04(0.000), evaluation_core_pigment_01(0.165), evaluation_core_pores_03(0.227), evaluation_core_composite_01(0.328), evaluation_core_acne_07(0.333)

## 해석 시 주의사항

- `Pooled Recall@40`의 분모는 681건 판정 풀에서 2~3점인 대표 anchor다. 전체 DB의 모든 관련 Case를 뜻하지 않는다.
- `Judged Precision@40`은 Top-40 중 판정된 문서만 분모로 삼는다. 미판정 문서를 0점으로 처리하지 않는다.
- Top-3는 실제 노출 120건을 모두 판정했으므로 nDCG·Precision·충돌 노출을 직접 해석할 수 있다.
- `corpus_ceiling_grade`는 전체 3,581건 전수 판정 상한이 아니라 현재 pooled anchor에서 확인된 최고 등급이다.
