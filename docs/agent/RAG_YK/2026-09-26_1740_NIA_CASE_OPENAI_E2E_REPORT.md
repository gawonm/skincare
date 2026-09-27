# NIA Case OpenAI 포함 End-to-End 성능 평가

> **정정:** 이 문서는 OpenAI가 제안한 route와 `IntentQueryPlanner`만 결합한 1차 진단이다.
> 실제 운영의 결정적 `RagRoutePolicy`를 적용한 최종 결과는
> `2026-09-26_1755_NIA_CASE_ROUTE_UPDATE_REPORT.md`를 기준으로 본다. 이 문서의 수치는
> 변경 전 원인을 추적하기 위한 이력으로만 보존한다.

## 결론

- OpenAI 운영 라우팅은 24건 중 22건(91.7%)을 Case RAG로 보냈다.
- 라우팅된 22건의 Case 질의는 모두 원문과 완전히 같아, 해당 건의 검색 결과는 동결된 v4 Live 결과와 동일하다.
- 2건은 `evidence_only`로 분류되어 Case 검색이 실행되지 않았다. 따라서 현재 병목은 질의 문장 생성이 아니라 Intent/RAG route gate다.

## 지표

| 범위 | 질의 수 | Case route | Success@40 | Recall@40 | Metadata Success@20 | Metadata Recall@20 | Metadata Retention@20 | Top-3 출력률 | Precision@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `retrieval_only` | 24 | 1.000 | 0.833 | 0.481 | 0.792 | 0.410 | 0.892 | 1.000 | 0.778 | 0.743 |
| `routed_conditional` | 22 | 1.000 | 0.864 | 0.488 | 0.818 | 0.413 | 0.886 | 1.000 | 0.803 | 0.733 |
| `end_to_end` | 24 | 0.917 | 0.792 | 0.466 | 0.750 | 0.395 | 0.842 | 0.917 | 0.736 | 0.672 |

- `retrieval_only`: 원문 질의를 Case 검색에 직접 넣었던 기존 v4 Live 기준선.
- `routed_conditional`: OpenAI가 Case RAG로 보낸 22건 안에서의 검색 품질.
- `end_to_end`: 라우팅 누락 2건을 검색 결과 없음(0점)으로 반영한 실제 시스템 성능.
- `Metadata Recall@20`: 전체 관련 anchor 대비 metadata Top-20에 남은 비율이다.

## 라우팅 실패 영향

### `evaluation_core_acne_04`

- 질의: 여드름 제품을 쓰면 뾰루지는 줄지만 얼굴이 따갑고 각질이 생깁니다. 계속 사용해도 될까요?
- 모델 판정: route=`evidence_only`, intents=`evidence_qa`
- LLM의 Case 질의 초안: 여드름 제품을 계속 사용해도 되는지에 대한 질문. 따가움과 각질에 대한 고민 포함
- 라우팅이 정상이라면 기존 검색 결과: Success@40=True, Recall@40=0.333, Precision@3=1.000, nDCG@3=1.000

### `evaluation_rare_sagging_01`

- 질의: 41살이고 볼과 턱선 처짐이 신경 쓰입니다. 화장품이 실제로 도울 수 있는 범위와 한계를 알고 싶어요.
- 모델 판정: route=`evidence_only`, intents=`evidence_qa`
- LLM의 Case 질의 초안: 41살, 볼과 턱선 처짐
- 라우팅이 정상이라면 기존 검색 결과: Success@40=False, Recall@40=0.000, Precision@3=0.000, nDCG@3=0.704

## 해석

- 라우팅 누락을 포함하면 Success@40은 0.833에서 0.792로, Precision@3은 0.778에서 0.736로 내려간다.
- `evaluation_core_acne_04`는 라우팅만 정상이라면 기존 Top-3가 모두 관련 문서였다. 이 건의 손실은 검색기나 리랭커가 아니라 route gate에서 발생했다.
- LLM은 실패 2건 모두 `query_plan.case_query` 초안을 생성했지만, `evidence_only` 판정 때문에 운영 planner가 이를 버렸다. 후속 수정 우선순위는 프롬프트 재작성보다 결정적 route 보정 규칙이다.
- OpenAI 호출은 24건 각각 1회였고 SDK 재시도는 0회였다.
