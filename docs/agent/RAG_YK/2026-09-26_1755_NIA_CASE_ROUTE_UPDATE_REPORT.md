# NIA Case 결정적 Route 보정 결과

## 결과

- 저장된 OpenAI 응답: 24건
- 수정 전 Case route: 22/24
- 수정 후 Case route: 23/24
- 복구: 2건
- 명시 성분으로 Case를 의도적으로 우회: 1건
- 회귀: 0건
- 원문과 완전히 같은 Case query: 24건
- 추가 OpenAI API 호출: 0회

## 수정 후 End-to-End

| 범위 | 질의 수 | Case route | Success@40 | Recall@40 | Metadata Success@20 | Metadata Retention@20 | Top-3 출력률 | Precision@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Case 대상 | 23 | 1.000 | 0.826 | 0.475 | 0.783 | 0.904 | 1.000 | 0.768 | 0.731 |
| 전체(명시 성분 우회 포함) | 24 | 0.958 | 0.792 | 0.454 | 0.750 | 0.858 | 0.958 | 0.736 | 0.701 |

전체 24건 표에서 명시 성분 우회 1건은 검색 실패가 아니라 다른 운영 경로를 선택한 것이며, 그 경로의 성능은 이 NIA Case 평가 범위에 포함하지 않는다.

## 복구된 질의

### `evaluation_core_acne_04`

- route: `evidence_only` → `claim_then_evidence`
- 보정 이유: `unspecified_ingredient_concern`
- Case query: 여드름 제품을 쓰면 뾰루지는 줄지만 얼굴이 따갑고 각질이 생깁니다. 계속 사용해도 될까요?

### `evaluation_rare_sagging_01`

- route: `evidence_only` → `claim_then_evidence`
- 보정 이유: `unspecified_ingredient_concern`
- Case query: 41살이고 볼과 턱선 처짐이 신경 쓰입니다. 화장품이 실제로 도울 수 있는 범위와 한계를 알고 싶어요.

## 적용 규칙

다음 조건을 모두 만족하는 피부 고민 요청을 `claim_then_evidence`로 보정한다.

1. 명시된 성분이 없다.
2. 피부 고민이 추출됐다.
3. LLM이 `query_plan.case_query` 초안을 생성했다.
4. Evidence 질문, 루틴 요청 또는 LLM의 Case route 제안이 있다.

명시 성분 Evidence 질문이나 Case 질의 초안이 없는 일반 정보 질문은 기존 `evidence_only`를 유지한다.
