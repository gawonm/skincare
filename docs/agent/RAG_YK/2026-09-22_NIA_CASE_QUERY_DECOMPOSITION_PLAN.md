# NIA Case 의도별 검색 질의 분리 및 메타데이터 리랭크 계획

> 작성: 2026-09-22 KST
>
> 상태: **구현 및 Agent 회귀 테스트 완료**
>
> 범위: 복합 사용자 요청의 의도별 질의 분리, NIA Case 검색·리랭크·성분 선별 질의 통일,
> Case 메타데이터를 포함한 BGE rerank

## 1. 문제

다음 복합 요청은 Intent 분류에 성공해도 하나의 `ParsedRequest.query`가 모든 단계에 재사용됐다.

```text
30대 남성, 요즘 환절기여서 힘들다. 여드름이 자꾸 올라오는 지성 피부인데
어떤 성분이 좋고 주의할 점은 뭐야? 추천 상품으로 3일간 스킨케어 루틴 짜줘
```

확인된 문제는 다음과 같다.

- LLM이 독립 질문으로 바꾸는 과정에서 `30대`, `남성`, `환절기`가 빠질 수 있다.
- Case 검색 질의에 이미 포함된 피부 고민이 `skin_concerns`로 다시 붙을 수 있다.
- Case 임베딩 검색과 BGE rerank, Case 관련 성분 선별이 서로 다른 질의를 사용할 수 있다.
- `추천 상품`, `3일간 루틴`처럼 Case 유사도와 무관한 지시가 rerank와 성분 선별에 들어간다.
- NIA Case의 연령·성별·피부 타입은 DB 메타데이터에 있고 기존 `embedding_text`에는 없다.

## 2. 확정한 해결 방식

이번 작업에서는 BM25 하이브리드 검색이나 SQL 메타데이터 가중치를 추가하지 않는다. 기존 벡터
검색으로 후보 20건을 회수하고, 저장된 Case 메타데이터를 후보 본문 앞에 붙여 BGE 교차 인코더가
최종 Top-3를 판단한다.

```text
원문 사용자 요청
  → 의도별 질의 분리
  → Case 전용 질의로 BGE-M3 벡터 Top-20
  → 같은 Case 전용 질의 + 후보 메타데이터로 BGE rerank
  → Top-3 Case에서 관련 성분 선별
  → Evidence → Product → Routine
```

예상 Case 전용 질의는 다음과 같다.

```text
30대 남성 환절기 여드름 지성 피부에 좋은 성분과 주의사항
```

`추천 상품`, `3일`, `루틴`은 Case 전용 질의에서 제외하고 각각 Product와 Routine 전용 질의에
보존한다.

## 3. Agent 설계

### 3.1 의도별 질의

`IntentQueryPlan`은 다음 질의를 분리해 보존한다.

- `case_query`: 사용자와 유사한 NIA Case를 찾고 관련 성분을 선별하는 질문
- `evidence_query`: 성분의 효능·주의·안전성 질문
- `product_query`: 상품 선택 요청과 상품 조건
- `routine_query`: 루틴 기간·일정·사용 요청

LLM이 구조화된 질의를 반환하고 `IntentQueryPlanner`가 명시적으로 적힌 연령대·성별·계절·피부
타입과 피부 고민이 Case 질의에서 빠지지 않게 보완한다. 이미 들어 있는 피부 고민은 다시 붙이지
않는다.

### 3.2 Case 단계별 질의 통일

다음 세 단계는 모두 동일한 `IntentQueryPlan.case_query`를 사용한다.

1. BGE-M3 임베딩과 DB Case 후보 검색
2. BGE Case rerank
3. Top-3 Case 관련 성분 선별

Case에서 선택한 성분을 공인 Evidence로 검증할 때는 `evidence_query`를 사용한다.

### 3.3 메타데이터 리랭크

BGE reranker의 후보 문서는 다음 형태로 조립한다.

```text
[사례 문맥]
연령: 34세
성별: 남성
피부 타입: 지성
피부 고민: 여드름/뾰루지

[질문·답변·추론]
...
```

메타데이터는 reranker 입력에만 덧붙이고 저장된 `page_content`는 변경하지 않는다. Case 문맥은
공식 Citation이나 공인 Evidence로 취급하지 않는다.

## 4. Backend 영향

Backend 코드는 변경하지 않는다.

- `BackendNiaCaseRetriever`는 이미 `age`, `gender`, `skin_type`, `skin_concerns`를
  `CaseSearchHit.metadata`로 반환한다.
- 기존 vector Top-20 검색 계약을 유지한다.
- 새 SQL, DB 컬럼, 모델, 마이그레이션, 설정 키, BM25 인덱스는 추가하지 않는다.
- 메타데이터의 최종 관련성 판단은 Agent의 BGE reranker가 담당한다.

## 5. 변경 파일

### 5.1 새 파일

| 파일 | 역할 |
| --- | --- |
| `agent/query_planning.py` | 원문·ParsedRequest를 의도별 `IntentQueryPlan`으로 정규화 |
| `tests/agent/test_query_planning.py` | 복합 요청 분리, 명시 문맥 보존, 중복 제거 회귀 테스트 |
| `docs/agent/RAG_YK/2026-09-22_NIA_CASE_QUERY_DECOMPOSITION_PLAN.md` | 계획과 구현 결과 |

### 5.2 수정 파일

| 파일 | 변경 |
| --- | --- |
| `agent/schemas.py` | `IntentQueryPlan`, `QueryPlanningRequest`, `ParsedRequest.query_plan` 추가 |
| `agent/prompts.py` | 전체 요청 보존과 Case/Evidence/Product/Routine 질의 분리 지시 |
| `agent/nodes.py` | RAG 경로 확정 뒤 query planner 적용, Product/Routine 전용 질의 사용 |
| `agent/rag_workflow.py` | Case 세 단계 질의 통일, Evidence 전용 질의 사용 |
| `agent/rag/retrieval/case_reranker.py` | 후보 원문 앞에 Case 메타데이터 문맥 추가 |
| `tests/agent/test_case_runtime_claim_processing.py` | reranker 메타데이터 입력 검증 |
| `tests/agent/test_case_two_layer_rag_workflow.py` | Case 검색·rerank·성분 선별 질의 일치 검증 |
| `docs/contracts/backend-to-agent.md` | 기존 Backend 응답 계약을 유지하는 Agent 내부 변경 기록 |

## 6. 검증 결과

```text
관련 테스트: 15 passed
Agent 전체 테스트: 179 passed
전체 테스트: 603 passed, 5 deselected
Ruff: passed
```

검증한 항목은 다음과 같다.

- 복합 요청의 Case 질의에 `30대`, `남성`, `환절기`, `지성`, `여드름`이 보존된다.
- Case 질의에는 `상품`, `3일`, `루틴`이 포함되지 않는다.
- Case 검색·rerank·성분 선별이 동일한 전용 질의를 사용한다.
- Product와 Routine 단계는 각각의 전용 질의를 사용한다.
- 피부 고민을 중복해서 붙이지 않는다.
- 명시 성분 Evidence 직행은 Case 질의를 만들지 않는다.
- BGE reranker가 Case 메타데이터와 원문을 함께 받는다.
- 기존 Agent 회귀 테스트가 모두 통과한다.

## 7. 후속 평가

실제 외부 LLM과 DB를 사용하는 Trace CLI에서 다음을 확인한다.

1. LLM이 `query_plan.case_query`에서 상품·루틴 지시를 제외하는지
2. 출력된 Case 검색 질의와 rerank 질의가 같은지
3. 연령·성별이 유사한 Case가 Top-3에 더 안정적으로 선택되는지
4. 벡터 Top-20에 필요한 Case가 들어오지 않는 recall 문제가 있는지

4번 문제가 골든셋에서 확인될 때만 벡터 후보 수 확대, 메타데이터 선호 후보 합집합 또는 BM25
하이브리드 검색을 별도 작업으로 검토한다.

## 8. 2026-09-23 Trace 회귀 보완

외부 LLM이 `case_query`에 `스킨케어 제품 뭘 써야 하지`를 남긴 실제 실행 결과를 확인했다.
기존 결정적 보정기는 누락된 사용자 문맥만 추가하고 상품·루틴 지시를 제거하지 않아, 프롬프트
준수 여부에 따라 Case 검색 질의가 다시 오염될 수 있었다.

다음 규칙을 추가한다.

- LLM의 Case 질의에 상품 선택 또는 루틴 실행 신호가 있으면 해당 질의를 그대로 사용하지 않는다.
- 원문에서 확인한 연령·성별·계절·피부 타입·피부 고민으로 Case 질의를 다시 구성한다.
- `N살` 표현도 연령 문맥으로 보존한다.
- 재구성된 하나의 질의를 Case 임베딩 검색·BGE rerank·Top-3 성분 선별에 동일하게 사용한다.
- Evidence 질의는 이번 보완 범위에서 변경하지 않는다.

예시 입력의 Case 전용 질의는 다음과 같다.

```text
30살 여성 겨울 민감성 건조 피부 관련 성분 및 주의사항
```
