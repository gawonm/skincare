# 2026-09-17 17:51 KST — 피부 고민형 Intent 라우팅 보정

## 1. 목적

피부 고민과 함께 무엇을 사용할지 묻는 질문이 LLM 응답 변동으로 `evidence_qa`로 분류되더라도,
Agent가 이를 결정적 규칙으로 `product_discovery`와 `claim_then_evidence`로 보정하도록 한다.

재현 질문:

```text
피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?
```

문제 발생 시 실행 결과:

```text
partial | evidence_qa
질문에 대한 근거: 검수된 근거가 없어 답변을 보류합니다.
```

## 2. 원인

- 동일 질문을 실제 `gpt-4o-mini`가 실행 시점에 따라 `product_discovery` 또는 `evidence_qa`로
  다르게 분류했다.
- 기존 `RagRoutePolicy`는 `PRODUCT_DISCOVERY` Intent가 이미 있을 때만 피부 고민을
  `CLAIM_THEN_EVIDENCE`로 보냈다.
- `EVIDENCE_QA`로 오분류된 경우에는 피부 고민과 사용 대상 탐색 표현이 있어도
  `EVIDENCE_ONLY`로 확정됐다.
- 경로만 보정하면 `TaskPlanBuilder`가 Product 작업을 추가하지 못하므로 Intent와 RAG 경로를
  함께 정규화해야 했다.

## 3. 적용 정책

| 사용자 표현 | 정규화 Intent | RAG 경로 |
| --- | --- | --- |
| 피부 고민 + “뭘 써”, “뭐 발라”, “어떤 성분”, “추천” | `product_discovery` | `claim_then_evidence` |
| 명시 성분 + 효능·주의·안전성 질문 | `evidence_qa` | `evidence_only` |
| 피부 고민의 원인 설명만 요청 | `evidence_qa` 유지 | `evidence_only` |
| 지원 상품 필터만 지정 | `product_discovery` | RAG 없이 Product 검색 |

LLM은 의미 해석을 담당하지만, 실행 Intent와 RAG 상태 전이는 Rule이 최종 확정한다. 이는
`TWO_LAYER_RAG_REFACTOR_PLAN.md`의 `DEC-010` 원칙을 따른다.

## 4. 코드 변경

### `agent/prompts.py`

- `product_discovery`와 `evidence_qa`의 의미를 명시했다.
- “피지가 많고 좁쌀이 나는데 뭘 써야 해?” 등 간접적인 사용·추천 표현 예시를 추가했다.
- 성분이 정해지지 않은 피부 고민 탐색에서는 `product_discovery` Intent와
  `claim_then_evidence` 경로를 함께 제안하도록 했다.

### `agent/rag_route_policy.py`

- `ProductDiscoveryCue` Enum으로 결정적 탐색 표현을 정의했다.
- 명시 성분이 없고 탐색 표현이 있으면 잘못 붙은 `evidence_qa`를 제거하고
  `product_discovery`를 추가한다.
- `RagRouteDecision.normalized_intents`로 보정된 Intent를 명시적으로 반환한다.
- 보정 사유를 `normalized_product_discovery`로 기록한다.

### `agent/nodes.py`

- `DECIDE_RAG_ROUTE` 노드가 보정된 Intent와 RAG 경로를 `ParsedRequest`에 함께 반영한다.
- 이후 `TaskPlanBuilder`가 Evidence 검증 뒤 Product 검색까지 실행할 수 있게 했다.

### `tests/agent/test_two_layer_rag.py`

- LLM이 재현 질문을 `evidence_qa + evidence_only`로 잘못 반환하는 사례를 추가했다.
- Rule 보정 후 호출 순서가 `Claim → Evidence → Product`인지 확인한다.
- Evidence 무결과에서도 Claim-only 상품과 제한 문구가 남는지 확인한다.
- “피지가 많은 원인이 뭐야?”는 Product 탐색으로 과잉 보정하지 않는 방어 테스트를 추가했다.

## 5. 실제 실행 결과

```text
실행 결과: partial | 의도: product_discovery
Claim 검색: 5건
Evidence 검색: 나이아신아마이드 3건(모두 미검수), 나머지 4건 무결과
최종 Citation: 0건
Claim-only 상품 후보: 13건
```

Evidence가 미검수이거나 없더라도 Claim은 탐색 정보로 유지됐으며, 상품에는
`Claim 기반·근거 미확인` 표시가 붙었다.

## 6. 검증 결과

```powershell
uv run pytest tests/agent/test_two_layer_rag.py -q
# 12 passed

uv run pytest tests -q
# 188 passed, 1 deselected

uv run ruff check agent tests/agent
# 통과

uv run pyrefly check agent tests/agent
# 0 errors
```

실제 `gpt-4o-mini`, BGE-M3, `skincare_latest` DB를 연결한 LangGraph 실행도 정상 완료했다.

## 7. 변경하지 않은 범위

- Claim/Evidence 저장 구조와 마이그레이션
- Backend 공개 계약과 API
- BGE-M3 및 리랭커 모델 설정
- Evidence 검수 기준과 Citation 생성 규칙
- 명시 성분 효능 질문의 `evidence_only` 정책

