# NIA Case 관리 조언 필터 보완: 24건 재평가

## 실행 범위

- Case 검색의 관리 조언 필터에서 명시적인 각질 제거 권고 표현을 보완했다.
- 질의 24건, 저장된 Dense Top-40 후보, BGE reranker v2-m3, OpenAI
  CareContext 예측을 세 버전에 동일하게 사용했다. CareContext 예측 2건은 재사용하고
  22건은 `gpt-4o-mini`로 새로 생성했다.
- 관련성 qrel은 기존 판정, 앞서 Codex가 판정한 6건, 이번에 새로 노출된 2건을
  합쳤다. 두 신규 판정은 [별도 JSONL](../../../tests/agent/nia_case_eval_data/nia_case_care_update_supplement_judgments_20260927_v1.jsonl)에 보존했다.
- 24건은 반복 개선에 사용한 개발셋이다. 아래 수치는 독립 성능 추정이 아니다.

## 동일 24건 비교

| 지표 | V5 기준 | 기존 CareContext 필터 | 이번 수정안 |
| --- | ---: | ---: | ---: |
| Case 결과가 있는 질의 | 24 | 23 | 22 |
| 관련 Case Hit@3 | 22 | 22 | 21 |
| 등급 3 Case Hit@3 | 17 | 17 | 16 |
| Precision@3 | 0.792 | 0.819 | 0.764 |
| nDCG@3 | 0.733 | 0.748 | 0.713 |
| 기존 qrel의 요청 방향 충돌 Case | 4 | 0 | 0 |
| 현재 Top-3 관련성 미판정 | 0 | 0 | 0 |

결과가 없는 질의도 Precision@3의 분모 3에 포함했다.
[수정안 순위](../../../tests/agent/nia_case_eval_data/nia_case_care_update_probe_20260927_v1.jsonl)와
[평가 요약](../../../tests/agent/nia_case_eval_data/nia_case_care_update_summary_20260927_v1.jsonl)을
남겼다. 요청 방향 충돌 코드는 전체 관리 조언 적합성 또는 임상 안전성 지표가 아니다.

## 바뀐 네 질의

| 질의 | 기존 필터 Top-3에서 제거한 관리 조언 | 수정안 결과 |
| --- | --- | --- |
| `evaluation_core_pigment_08` | 필링 후 따가움에도 정기적인 각질 관리 권고 | 등급 2, 1, 1 |
| `evaluation_core_acne_04` | 따가움을 호소하는 사용자에게 각질을 부드럽게 제거하도록 권고 | 등급 2, 3, 2 |
| `evaluation_core_composite_01` | 붉고 건조한 볼의 부위 제한 없이 각질 제거를 권하는 3건 | Case 결과 보류 |
| `evaluation_rare_dry_02` | 입가 갈라짐·따가움에도 주기적인 각질 관리 권고 | 등급 3, 1, 3 |

확인된 각질 제거 권고 6건은 수정안 Top-3에서 빠졌다. 복합 질의의 보류 때문에
관련성 Hit@3과 nDCG@3이 낮아졌다. 후보를 비운 이유를 성능 비교에서 숨기지 않는다.

## CareContext 독립 판정

24개 질의의 원문만 읽고 자극 상태와 관리 우선순위를 따로 판정했다.
[판정·원문 구절](../../../tests/agent/nia_case_eval_data/nia_case_care_context_independent_judgments_20260927_v1.jsonl)과
[차이 요약](../../../tests/agent/nia_case_eval_data/nia_case_care_context_audit_summary_20260927_v1.jsonl)을
보존했다. 이는 OpenAI 출력과 독립적으로 수행한 Codex 판정이며 피부과 전문의
판정은 아니다.

| 항목 | 일치 |
| --- | ---: |
| 자극 상태 | 21/24 |
| 관리 우선순위 | 19/24 |
| 필터 발동 조건 `active`와 `recovery` 동시 충족 | 24/24 |

이번 24건에서는 필터 발동 오류가 보이지 않았으므로 CareContext 스키마나
프롬프트는 변경하지 않았다. 개별 값이 다른 7건은 별도 질의에서 다시 확인해야 한다.

## 남은 관리 조언 부적합

이번 규칙은 명시적인 각질 제거·강한 세안 권고를 겨냥한다.
`evaluation_rare_sensitive_01`은 사용자가 성분을 늘리기 전에 피부를 안정시키려
하지만, 현재 Top-3 중 두 답변이 새 세럼·앰플 사용을 바로 권한다.
이는 기존 필터와 이번 수정안에 모두 남았다. 따라서 관리 조언 전체의 부적합
노출을 0으로 보고할 수 없다.

[12개 후보의 별도 Codex 관리 적합성 판정](../../../tests/agent/nia_case_eval_data/nia_case_care_semantic_probe_judgments_20260927_v1.jsonl)에서
부적합으로 판정한 후보의 Top-3 노출은 기존 필터 8건, 수정안 2건이다.
양쪽 Top-3의 나머지 후보 전부를 이 파일에서 판정한 것은 아니므로 이 값은
전체 부적합 노출률이 아니라 **판정한 후보 중 확인된 최소 건수**다.

## 구조화 판정 오프라인 비교

`행위 / 권고·금지 / 적용 시점 / 부위 / 답변 원문 구절`을 구조화하는
[오프라인 비교 코드](../../../tests/agent/evaluate_nia_case_care_semantic_probe.py)와
[OpenAI 전송 검토용 12건의 질의·사례 질문·답변](../../../tests/agent/nia_case_eval_data/nia_case_care_semantic_probe_payload_20260927_v1.jsonl)을 준비했다.
첫 OpenAI 호출은 자동 승인 검토에서 거절됐다. 사유는 로컬 NIA 후보 답변 12건의
구체적 입력과 목적지에 대한 명시적 승인이 없다는 것이었다. 이후 사용자가 위 12건을
`gpt-4o-mini`로 전송하는 데 명시적으로 동의해, 동일 입력으로 평가를 실행했다.
[구조화 출력 12건](../../../tests/agent/nia_case_eval_data/nia_case_care_semantic_probe_results_20260927_v1.jsonl)을
원문과 함께 보존했다.

| 항목 | 결과 |
| --- | ---: |
| Codex의 별도 관리 적합성 판정과 일치 | 5/12 |
| `부적합` 8건 중 찾아낸 건수 | 1/8 |
| `부합` 4건 중 부합으로 판정한 건수 | 4/4 |
| 실제 답변에 존재하는 인용 구절 | 11/12 |

한 번의 프롬프트·동일한 개발 사례 12건에 대한 소규모 비교다. 모델은 각질 제거
권고가 있어도 함께 쓰인 보습·진정 성분에 초점을 맞춰 `부합`으로 분류하는 오류를
반복했다. `evaluation_rare_sensitive_01`의 성분 추가 권고도 회복 우선 요청과
충돌한다고 보지 않았다. 이 구조화 모델을 그대로 운영 필터에 추가하지 않는다.
입력·출력 토큰과 호출 비용은 기록하지 않았으므로 비용 개선 결론도 내리지 않는다.

## 개발 24건에 쓰지 않은 기존 질의 12건

[기존 40건 의미 평가 자료](../../../tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_queries_v1.jsonl)에서
이번 24건에 포함되지 않은 질의 12건을 골랐다. 이 질의들은 프로젝트의 과거
검색 평가에 사용된 적이 있으므로 완전히 새로운 독립 테스트셋은 아니다.
[수동 CareContext와 근거 구절](../../../tests/agent/nia_case_eval_data/nia_case_care_holdout_contexts_20260927_v1.jsonl)을
고정하고, 동일 Dense Top-40을 BGE로 재정렬한 뒤 필터 전후를 비교했다.
[12건 결과](../../../tests/agent/nia_case_eval_data/nia_case_care_holdout_probe_20260927_v1.jsonl)를
보존했다. 이 비교에는 새 OpenAI 호출이 없다.

- Case 출력 질의: 12 → 11건. Top-3 구성이 바뀐 질의: 3건.
- `evaluation_core_pores_06`: 면도 뒤 볼 따가움에도 각질 제거·딥 클렌징을
  권하던 세 사례가 빠지고, 적합 후보가 남지 않아 결과를 보류했다.
- `evaluation_core_pigment_07`: 따가운 피부에 BHA 또는 살리실산·레티놀을
  권하는 두 사례가 빠졌다. 새 Top-3는 주로 여드름 관리 사례여서
  색소·붉은 자국 질문과의 관련성은 별도로 판정해야 한다.
- `evaluation_rare_redness_03`: 각질 제거를 필수 관리로 설명한 사례가
  빠지고 진정·보습 사례로 교체됐다.
- `evaluation_core_composite_03`: 산 성분·레티놀 병용 후 붉고 아프다는
  질문인데 Top-3가 모두 미백 제품 사용 사례로 남았다. 이 필터의 표현 범위
  밖에 있는 **검색 관련성·현재 사용 시점 문제**다.

위 12건의 Top-3 전체에 이번 관련성 qrel과 관리 조언 적합성 판정을 새로
부여하지 않았다. 따라서 이 결과로 독립 Hit@3·nDCG@3이나 전체 부적합
노출률을 계산하지 않는다.

## 검증과 다음 게이트

후속 [새 복합 질의 12건 점검](2026-09-27_NIA_CASE_FRESH_COMPOSITE_CHALLENGE_REPORT.md)은
합성 도전셋으로 별도 집계했다. 아래 개발 24건과 합쳐 하나의 성능 수치로 계산하지 않는다.

- Case 정책 회귀 테스트와 Agent 전체 테스트: **356개 통과**.
- 수정안 평가: 24개 질의 완료, 신규 관련성 판정 2건 반영, 최종 미판정 0건.
- Ruff 검사 통과. 구조화 판정 비교는 사용자 승인 후 12건 실행했다.
- 발표용 최종 성능 비교 전에는 남은 관리 부적합 후보의 전체 판정과
  완전히 새로운 복합 질의의 관련성·관리 적합성 판정이 필요하다.
- Product·Evidence RAG, DB, 공용 설정은 변경하지 않았다.
