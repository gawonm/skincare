# NIA Case CareContext 전체 골든셋 점검

## 실행 조건

- 질의: 24건, OpenAI 모델: `gpt-4o-mini`
- CareContext 예측 출처: OpenAI 응답 22건, 앞선 동일 모델 집중 평가 재사용: 2건
- Dense Top-40 저장 후보와 BGE reranker v2-m3를 동일하게 사용했다.
- 현재 후보의 관리 적합성 정책에 구조화 CareContext를 전달했다.
- 관련성 판정 출처: 기존 판정과 Codex의 추가 관련성 판정 6건.

## 결과

| 항목 | 기준 | 현재 |
| --- | ---: | ---: |
| Case 출력 질의 | 24 | 23 |
| 관련 Case 포함 질의 (전체 24건) | 22 | 22 |
| 등급 3 포함 질의 (전체 24건) | 17 | 17 |
| 기존 qrel의 요청 방향 충돌 Case | 4 | 0 |
| nDCG@3 (전체 24건) | 0.733 | 0.748 |

- 회복 우선으로 분류된 질의: 12건
- 현재 Top-3 미판정 후보: 0건
- 빈 Case 결과는 분모 3의 실패로 남기고, qrel 없는 후보를 관련 사례로 간주하지 않는다.

## 같은 판정 분모에서의 비교

- 양쪽 Top-3가 모두 판정된 질의: 24건
- 관련 Case 포함: 22 → 22건
- 등급 3 포함: 17 → 17건
- Precision@3: 0.792 → 0.819
- nDCG@3: 0.733 → 0.748
- 추가 판정 6건은 같은 골든셋을 검토한 Codex의 판정이므로 독립 검증셋의 개선 수치가 아니다.

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
| `evaluation_core_pigment_08` | yes | 5 | 2,2,1 | 2,2,1 | 0 |
| `evaluation_core_acne_01` | no | 6 | 3,3,3 | 3,3,3 | 0 |
| `evaluation_core_acne_03` | no | 3 | 3,3,3 | 3,3,3 | 0 |
| `evaluation_core_acne_04` | yes | 8 | 3,2,3 | 2,3,2 | 0 |
| `evaluation_core_acne_05` | no | 7 | 3,3,2 | 3,3,2 | 0 |
| `evaluation_core_acne_08` | yes | 11 | 2,3,2 | 2,3,3 | 0 |
| `evaluation_core_composite_01` | yes | 9 | 2,2,2 | 3,3,2 | 0 |
| `evaluation_core_composite_02` | yes | 8 | 3,2,2 | 2,2,2 | 0 |
| `evaluation_core_composite_06` | yes | 8 | 3,3,3 | 3,2,2 | 0 |
| `evaluation_rare_dry_02` | yes | 7 | 2,3,1 | 3,1,2 | 0 |
| `evaluation_rare_dry_03` | yes | 6 | 2,3,1 | 3,3,3 | 0 |
| `evaluation_rare_redness_02` | yes | 6 | 3,3,3 | 3,3,3 | 0 |
| `evaluation_rare_wrinkles_02` | no | 6 | 3,2,3 | 3,2,3 | 0 |
| `evaluation_rare_sensitive_01` | yes | 6 | 2,2,0 | 2,2,2 | 0 |
| `evaluation_rare_sagging_01` | no | 0 | 1,1,0 | 1,1,0 | 0 |

## 해석 기준

- 이 코퍼스의 Q&A 답변은 사례 탐색 자료이며 독립적인 성분 효능 증거가 아니다.
- qrel은 코퍼스 전체의 완전 판정이 아니므로 Dense 내 관련 후보 수는 확인된 하한이다.
- qrel의 요청 방향 충돌 코드는 독립적인 임상 안전성 라벨이 아니다. 위 충돌 수를 전체 안전성 성능으로 해석하지 않는다.
- Codex 추가 판정은 기존 등급 기준을 따른 동일 작업자의 판정이다. 독립 검증셋 성능으로 표시하지 않는다.
- 회복 우선 상태의 피부 해석 자체는 독립적인 정답 라벨이 아직 없다.

## 프로젝트 목표와 구현 점검

- 목표: 유사 NIA 사례를 찾고, 별도 Evidence로 성분 주장을 검증한 뒤 제품·루틴을 설명한다. NIA 답변을 효능 근거로 승격하지 않는다.
- 현재 Case 경로의 Dense Top-40 → BGE Top-3 → Claim 추출은 사례 탐색이라는 앞단 목표와 맞는다. 관리 적합성 필터도 안전성 보완에 해당한다.
- Codex 판정 보강 후 24건의 Precision@3·nDCG@3는 상승했지만 Case 출력은 24→23건이다. 이 판정은 기존 골든셋을 확인한 동일 작업자의 결과이므로 독립 성능 입증은 아니다.
- `evaluation_core_pores_08`은 Dense Top-40에 판정 관련 후보가 없고 필터 후 Case가 0개다. 필터 조정보다 후보 풀의 커버리지와 결과 없음 처리가 먼저 필요하다.
- `evaluation_rare_sagging_01`도 Dense Top-40에서 판정 관련 후보가 0개다. 현재 코퍼스·검색 범위의 한계로 분리해 추적한다.
- `evaluation_core_acne_04`, `evaluation_core_composite_02`에서 등급 3 사례가 필터로 빠졌다. 각 답변의 자극성 관리 권고와 qrel 안전 판정의 차이를 재검토해야 한다.
- `evaluation_rare_wrinkles_02`는 따가움이 있는데 CareContext가 active/standard라 필터 조건이 꺼진다. CareContext의 독립 상태 정답을 먼저 만들어 누락과 과잉 분류를 확인해야 한다.
- 리랭커 예외 시에도 벡터 후보에 같은 관리 적합성 검사를 적용하고, 적합 후보가 없으면 Claim 추출을 건너뛰도록 수정했다. 이 실패 경로는 별도 테스트로 확인했다.
- 우선순위: 관리 적합성 별도 판정과 필터 누락 점검 → CareContext 상태 평가 → Dense 커버리지와 빈 결과 처리 → 독립 복합 질의 평가. Evidence DB 확충은 뒤 순서로 둔다.

## Codex가 추가 판정한 6건

| 질의 ID | review_key | 관련성 등급 | 판정 근거 |
| --- | --- | ---: | --- |
| `evaluation_core_pigment_08` | `3a477fcc27b4a0ea` | 1 | 기미·색소침착은 직접 일치하지만 잦은 필링 뒤 건조·따가움과 회복 우선 요청을 다루지 않는다. 장벽 강화라는 성분 효능 언급만으로 현재 상태에 맞는 회복 루틴을 제시했다고 보지 않는다. |
| `evaluation_core_acne_08` | `e726d473cab61d7f` | 3 | 30대 남성의 면도 후 입가·턱 여드름과 자극 최소화 요청을 직접 다루고 순한 세안·면도 후 진정·보습 루틴을 제시한다. 성분 효능의 독립 근거 여부는 이 관련성 판정에 포함하지 않는다. |
| `evaluation_core_composite_01` | `8d575f2455c903b4` | 2 | T존 유분·모공과 U존 건조에 부위별 보습 루틴을 제시하지만 사용자가 함께 언급한 볼 붉어짐과 그 상태에서의 관리 강도 조절은 빠져 있다. 이중 세안·반복 각질 제거 권고는 별도 관리 적합성 검토 대상으로 남긴다. |
| `evaluation_core_composite_06` | `79be17110a031135` | 2 | 복합성 피부의 붉은 여드름과 순한 세안·보습 방향은 일부 맞지만 번들거림·모공과 세안 직후 따가움의 동시 상황을 직접 다루지 않는다. |
| `evaluation_core_composite_06` | `f74266f25523025d` | 2 | 복합성 피부의 T존 유분과 여드름, 순한 세안·보습은 관련 있으나 현재의 세안 후 따가움·붉은 여드름·모공 고민을 함께 해결하는 설명은 부족하다. |
| `evaluation_rare_dry_03` | `f91a0986caddfa40` | 3 | 과각질과 심한 건조를 장벽 손상 문맥으로 설명하고 과도한 물리·화학적 각질 제거를 피하며 진정·보습을 우선하라고 직접 답한다. 필링 후 악화라는 원인은 문서 질문에 없지만 핵심 관리 방향은 일치한다. |

관련성 판정과 별도로 [현재 관리 조언 적합성 검토](2026-09-27_NIA_CASE_CARE_APPLICABILITY_AI_REVIEW.md)를 수행했다. 기존 qrel의 요청 방향 충돌 4→0은 이 검토의 전체 결과가 아니다.
