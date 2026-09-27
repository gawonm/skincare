# NIA Case 다음 업데이트 판정 요청과 실험 기준

> 후속 상태: Codex가 미판정 6건의 코퍼스 관련성을 판정했다.
> [전체 24건 비교](2026-09-27_NIA_CASE_CARE_CONTEXT_AI_JUDGED_REPORT.md)와
> [현재 관리 조언 적합성 검토](2026-09-27_NIA_CASE_CARE_APPLICABILITY_AI_REVIEW.md)를 참고한다.
> 아래 목록은 판정 요청 당시의 범위를 보존한다.

## 판정을 분리하는 이유

현재 코퍼스 qrel의 `relevance_grade`는 질의와 사례의 **검색 관련성**을 평가한다.
`direction_conflicts`도 사용자의 요청 목표와 사례 답변의 충돌 코드이며,
독립적인 임상 안전성 라벨이 아니다. 따라서 기존 값을 안전성 정답으로 바꾸거나
관련성 등급을 임의로 낮추지 않는다.

후보마다 아래 두 판단을 독립적으로 남긴다.

1. 관련성: 기존 0~3 등급과 고민·문맥·요청 적합성 점수. 기존 qrel 정책을 따른다.
2. 현재 관리 적합성: 적합 / 부적합 / 판정 보류. 사용자에게 **지금** 적용하라고
   권하는 관리인지, 피하라는 설명인지, 회복 뒤의 조건부 권고인지 구분하고
   해당 원문 구절을 기록한다. 이 값은 기존 qrel과 별도로 보관한다.

## 새 Top-3 중 판정이 필요한 6건

전체 질문·답변은 [미판정 후보 파일](../../../tests/agent/nia_case_eval_data/nia_case_care_context_full_golden_unjudged_20260927_v1.jsonl)에 있다.
기존 보완 판정이 있는 `evaluation_rare_sensitive_01` 후보는 이 목록에서 제외한다.

| 질의 ID | 블라인드 review_key | 확인할 문맥 |
| --- | --- | --- |
| `evaluation_core_pigment_08` | `3a477fcc27b4a0ea` | 필링 뒤 따가움·건조와 색소 고민을 함께 다루는가 |
| `evaluation_core_acne_08` | `e726d473cab61d7f` | 면도 뒤 턱선 자극과 여드름을 함께 다루는가 |
| `evaluation_core_composite_01` | `8d575f2455c903b4` | T존 피지·모공과 볼의 붉음·건조를 함께 다루는가 |
| `evaluation_core_composite_06` | `79be17110a031135` | 번들거림, 세안 뒤 따가움, 모공·붉은 여드름을 함께 다루는가 |
| `evaluation_core_composite_06` | `f74266f25523025d` | 같은 복합 상태와 현재 관리 방향이 맞는가 |
| `evaluation_rare_dry_03` | `f91a0986caddfa40` | 필링 뒤 악화된 건조·통증과 보습 우선 요청에 맞는가 |

## 관련성 등급 3이지만 새 필터에서 제외된 2건

전체 본문은 [고정 Dense 후보 풀](../../../tests/agent/nia_case_eval_data/nia_case_corpus_relative_live_pool_20260926_1416_v1.jsonl)에 있다.
두 건은 기존 qrel의 요청 방향 충돌 코드가 비어 있다. 관련성이 높다는 판정과
현재 관리 적합성이 다를 수 있으므로 두 판단을 각각 재검토한다.

| 질의 ID | Case ID / review_key | 판정이 필요한 조언 |
| --- | --- | --- |
| `evaluation_core_acne_04` | `COT_ACN_F_O30_01785` / `61af5c57ae496bdb` | 장벽 진정 우선 설명과 함께 BHA 스팟 제품 소량 사용을 권함 |
| `evaluation_core_composite_02` | `COT_ACN_F_U20_05338` / `2e6917e2513d6147` | 진정·보습 루틴과 함께 주 1~2회 각질 제거를 권함 |

## CareContext 독립 판정

[24건 구조화 예측](../../../tests/agent/nia_case_eval_data/nia_case_care_context_full_golden_predictions_20260927_v1.jsonl)은
OpenAI 출력이므로 상태 정답으로 사용하지 않는다. 각 질의에 대해 현재 자극 상태
`active / inactive / unknown`과 관리 우선순위 `recovery / standard / unknown`을
원문에 근거해 독립적으로 판정해야 두 필드의 정확도를 계산할 수 있다.
`evaluation_rare_wrinkles_02`의 따가움과 `active/standard`, 일반적인 자극 최소화
요청에서 나온 `unknown/recovery` 등의 경계를 특히 확인한다.

## 판정 후 비교 실험

- Dense Top-40과 BGE 점수, 질의 24건을 고정해 기존 V5와 관리 적합성 필터 적용 버전을 비교한다.
- 관련성은 Hit@3, Precision@3, 등급 3 Hit@3, nDCG@3로 본다.
- 관리 적합성은 부적합 Case 노출, 적합 후보가 있는데도 보류한 질의,
  적합 후보가 없어서 보류한 질의를 별도로 센다.
- 미판정 후보가 남으면 전체 24건의 개선 결론과 안전성 결합 지표를 발표 수치로 확정하지 않는다.
- 현재 24건은 반복 개선에 사용했으므로, 최종 버전에는 별도의 미사용 복합 질의를
  판정해 검증한다. 이전 종합 사례 3건은 오류 분석 자료로 두고 독립 성능 추정치로 쓰지 않는다.

Evidence DB의 검수 상태와 Product RAG 출력 적합성은 별도 평가로 남긴다.
