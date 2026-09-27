# NIA Case CareContext 전체 골든셋 점검

## 실행 조건

- 질의: 24건, OpenAI 모델: `gpt-4o-mini`
- 이번 실행의 새 OpenAI 응답: 22건, 앞선 동일 모델 집중 평가 재사용: 2건
- Dense Top-40 저장 후보와 BGE reranker v2-m3를 동일하게 사용했다.
- 현재 후보의 관리 적합성 정책에 구조화 CareContext를 전달했다.
- 관련성은 기존 코퍼스 상대 골든 v5 및 확정 보완 판정만 사용했다.

## 결과

| 항목 | 기준 | 현재 |
| --- | ---: | ---: |
| Case 출력 질의 | 24 | 23 |
| 관련 Case 포함 질의 (전체 24건) | 22 | 판정 보류 |
| 등급 3 포함 질의 (전체 24건) | 17 | 판정 보류 |
| 기존 qrel의 요청 방향 충돌 Case | 4 | 0 |
| nDCG@3 (전체 24건) | 0.733 | 판정 보류 |

- 회복 우선으로 분류된 질의: 12건
- 현재 Top-3 미판정 후보: 6건
- 빈 Case 결과는 분모 3의 실패로 남기고, qrel 없는 후보를 관련 사례로 간주하지 않는다.

## 같은 판정 분모에서의 비교

- 양쪽 Top-3가 모두 판정된 질의: 19건
- 관련 Case 포함: 17 → 17건
- 등급 3 포함: 14 → 13건
- Precision@3: 0.772 → 0.789
- nDCG@3: 0.763 → 0.744
- 미판정 후보가 있는 질의는 양쪽 비교에서 제외했다. 전체 24건의 개선 수치로 해석하지 않는다.

## 질의별 진단

| ID | 회복 우선 | Dense 내 판정 관련 | 기준 등급 | 현재 등급 | 미판정 |
| --- | --- | ---: | --- | --- | ---: |
| `evaluation_core_pores_01` | no | 8 | 3,3,2 | 3,3,2 | 0 |
| `evaluation_core_pores_02` | no | 6 | 3,3,2 | 3,3,2 | 0 |
| `evaluation_core_pores_03` | no | 6 | 3,3,2 | 3,3,2 | 0 |
| `evaluation_core_pores_05` | no | 6 | 2,2,2 | 2,2,2 | 0 |
| `evaluation_core_pores_08` | yes | 0 | 0,0,0 | 결과 없음 | 0 |
| `evaluation_core_pigment_01` | no | 2 | 3,1,3 | 3,1,3 | 0 |
| `evaluation_core_pigment_02` | no | 5 | 3,3,3 | 3,3,3 | 0 |
| `evaluation_core_pigment_04` | yes | 4 | 1,2,1 | 1,2,1 | 0 |
| `evaluation_core_pigment_05` | no | 2 | 3,1,1 | 3,1,1 | 0 |
| `evaluation_core_pigment_08` | yes | 5 | 2,2,1 | 2,2,? | 1 |
| `evaluation_core_acne_01` | no | 6 | 3,3,3 | 3,3,3 | 0 |
| `evaluation_core_acne_03` | no | 3 | 3,3,3 | 3,3,3 | 0 |
| `evaluation_core_acne_04` | yes | 8 | 3,2,3 | 2,3,2 | 0 |
| `evaluation_core_acne_05` | no | 7 | 3,3,2 | 3,3,2 | 0 |
| `evaluation_core_acne_08` | yes | 10 | 2,3,2 | 2,3,? | 1 |
| `evaluation_core_composite_01` | yes | 8 | 2,2,2 | 3,3,? | 1 |
| `evaluation_core_composite_02` | yes | 8 | 3,2,2 | 2,2,2 | 0 |
| `evaluation_core_composite_06` | yes | 6 | 3,3,3 | 3,?,? | 2 |
| `evaluation_rare_dry_02` | yes | 7 | 2,3,1 | 3,1,2 | 0 |
| `evaluation_rare_dry_03` | yes | 5 | 2,3,1 | ?,3,3 | 1 |
| `evaluation_rare_redness_02` | yes | 6 | 3,3,3 | 3,3,3 | 0 |
| `evaluation_rare_wrinkles_02` | no | 6 | 3,2,3 | 3,2,3 | 0 |
| `evaluation_rare_sensitive_01` | yes | 6 | 2,2,0 | 2,2,2 | 0 |
| `evaluation_rare_sagging_01` | no | 0 | 1,1,0 | 1,1,0 | 0 |

## 해석 기준

- 이 코퍼스의 Q&A 답변은 사례 탐색 자료이며 독립적인 성분 효능 증거가 아니다.
- qrel은 코퍼스 전체의 완전 판정이 아니므로 Dense 내 관련 후보 수는 확인된 하한이다.
- qrel의 요청 방향 충돌 코드는 독립적인 임상 안전성 라벨이 아니다. 위 충돌 수를 전체 안전성 성능으로 해석하지 않는다.
- 미판정 후보가 있으면 전체 성능 개선 결론과 전체 nDCG@3 산출을 보류한다.
- 회복 우선 상태의 피부 해석 자체는 독립적인 정답 라벨이 아직 없다.

## 프로젝트 목표와 구현 점검

- 목표: 유사 NIA 사례를 찾고, 별도 Evidence로 성분 주장을 검증한 뒤 제품·루틴을 설명한다. NIA 답변을 효능 근거로 승격하지 않는다.
- 현재 Case 경로의 Dense Top-40 → BGE Top-3 → Claim 추출은 사례 탐색이라는 앞단 목표와 맞는다. 관리 적합성 필터도 안전성 보완에 해당한다.
- 다만 Case 출력 1건 누락과 판정 완료분의 등급 3·nDCG 하락은 관련성 유지 목표를 충족하지 못한다. 안전 필터 성과만으로 채택을 확정하기 어렵다.
- `evaluation_core_pores_08`은 Dense Top-40에 판정 관련 후보가 없고 필터 후 Case가 0개다. 필터 조정보다 후보 풀의 커버리지와 결과 없음 처리가 먼저 필요하다.
- `evaluation_rare_sagging_01`도 Dense Top-40에서 판정 관련 후보가 0개다. 현재 코퍼스·검색 범위의 한계로 분리해 추적한다.
- `evaluation_core_acne_04`, `evaluation_core_composite_02`에서 등급 3 사례가 필터로 빠졌다. 각 답변의 자극성 관리 권고와 qrel 안전 판정의 차이를 재검토해야 한다.
- `evaluation_rare_wrinkles_02`는 따가움이 있는데 CareContext가 active/standard라 필터 조건이 꺼진다. CareContext의 독립 상태 정답을 먼저 만들어 누락과 과잉 분류를 확인해야 한다.
- 리랭커 예외 시에도 벡터 후보에 같은 관리 적합성 검사를 적용하고, 적합 후보가 없으면 Claim 추출을 건너뛰도록 수정했다. 이 실패 경로는 별도 테스트로 확인했다.
- 우선순위: 새 Top-3 미판정 6건과 상충 사례의 관련성·안전성 판정 → CareContext 상태 평가 → Dense 커버리지와 빈 결과 처리 → 필터 강도 재조정. Evidence DB 확충은 뒤 순서로 둔다.
