# 2-Layer RAG Agent — main 대비 변경점

## 1. 비교 기준

- 점검일: 2026-09-17
- 원격 기준: `origin/main` `b6ef764`
- 현재 브랜치: `feature/agent-two-layer-rag-main`
- 후속 통합 작업 시작 기준 커밋: `42fa02a` (`docs(agent): Claim 검증 구현 일지 갱신`)
- 정책 기준: [`TWO_LAYER_RAG_REFACTOR_PLAN.md`](TWO_LAYER_RAG_REFACTOR_PLAN.md)

현재 브랜치는 `origin/main`을 포함하며, Agent 전용 커밋과 아직 커밋하지 않은 Agent 통합 변경이
추가된 상태다. 이 문서는 이전 `feature/rag-pipeline` 부모 브랜치가 아니라 현재 로컬 작업 트리를
기준으로 설명한다.

현재 변경 범위는 `agent/`, `tests/agent/`, `docs/agent/`이다. Backend, Data, 모델, 마이그레이션,
공용 설정은 변경하지 않았다.

## 2. LangGraph 흐름 변경

공통 진입 흐름은 다음과 같다.

```text
UNDERSTAND_REQUEST
  → DECIDE_RAG_ROUTE
  → RESOLVE_ENTITIES
  → ASSESS_INFORMATION
  → ROUTE_TASK
```

`DECIDE_RAG_ROUTE`에서 LLM의 경로 제안을 그대로 실행하지 않고 `RagRoutePolicy`가 Intent, 명시
성분, 피부 고민, 상품 필터와 후보 참조를 검사해 최종 경로를 확정한다.

### 명시 성분 근거 질문

```text
ROUTE_RAG
  → SEARCH_EVIDENCE
  → ASSEMBLE_RAG_RESPONSE
  → VALIDATE_RESULT
```

예: `나이아신아마이드 효능과 주의를 알려줘`

- `rag_route=evidence_only`
- Claim 검색을 호출하지 않는다.
- 식별된 표준 성분 ID로 Evidence를 바로 검색한다.

### 피부 고민 기반 상품 탐색

```text
ROUTE_RAG
  → SEARCH_CLAIMS
  → RESOLVE_CLAIM_INGREDIENTS
  → VERIFY_CLAIMS
  → BUILD_RECOMMENDATION_CANDIDATES
  → ASSEMBLE_RAG_RESPONSE
  → PROCESS_TASK(Product)
  → VALIDATE_RESULT
```

예: `피지가 많고 좁쌀 여드름이 나는데 세럼 추천해줘`

- `rag_route=claim_then_evidence`
- NIA Claim에서 후보 성분을 찾는다.
- Data가 `MATCHED`로 전달한 `ingredient_id`는 Agent에서 다시 문자열 매칭하지 않는다.
- 미확정 anchor만 `IngredientRepository`로 보완 식별한다.
- Claim statement마다 Evidence를 독립적으로 확인한다.
- Evidence가 확인된 성분은 `EVIDENCE_SUPPORTED`, 근거를 찾지 못한 성분은 `CLAIM_ONLY`가 된다.
- 두 등급 모두 Product RDB 검색 대상이지만 응답 표현·순서·Citation을 분리한다.
- Evidence 도구 오류, 미지원, 명시적 상반 근거가 있는 성분은 상품 후보에서 보류하거나 제외한다.

### 상품 조건 또는 기존 후보 기반 탐색

명시 성분 상품 검색, 상품 속성 필터, 기존 후보 번호 참조는 Claim/Evidence RAG를 호출하지 않고
Product RDB 경로로 처리한다. 후보 번호가 가리키는 분류가 현재 지원 목록에서 제거됐다면 조회 전에
미지원 조건으로 반환한다.

## 3. State와 DTO 변경

`AgentState`의 주요 2-Layer RAG 필드는 다음과 같다.

| 필드 | 타입 | 역할 |
| --- | --- | --- |
| `rag_route` | `RagRoute` | `evidence_only`와 `claim_then_evidence` 분기 |
| `claim_bundle` | `ClaimBundle` | NIA 탐색 Claim과 statement별 성분 anchor 보관 |
| `claim_verification_bundle` | `ClaimVerificationBundle` | Claim별 Evidence 판정 상태·근거 보관 |
| `recommendation_ingredients` | `IngredientRecommendationSet` | 상품 조회에 사용할 근거 등급별 성분 후보 |
| `evidence_bundle` | `EvidenceBundle` | 명시 성분 Evidence 직접 질문 결과 보관 |

Claim DTO는 `agent/rag/claim_schemas.py`에 별도로 정의한다. Claim과 `EvidenceRecord` 사이에
상속이나 공용 결과 타입을 만들지 않아 사용자 경험담이 Evidence 인용으로 렌더링되는 경로를
차단한다.

주요 검증 규칙은 다음과 같다.

- `MATCHED` anchor에는 `ingredient_id`가 반드시 있어야 한다.
- 미확정 anchor에는 `ingredient_id`를 넣을 수 없다.
- Agent는 `APPROVED` Claim만 처리한다.
- 중복 `statement_id`와 중복 대상 성분 ID는 계약 오류로 중단한다.
- `SUPPORTED` 결과에는 실제 검색 결과와 일치하는 Evidence record와 요약이 필요하다.
- `SUPPORTED`가 아닌 Claim 결과에는 Citation 가능한 Evidence를 넣을 수 없다.

## 4. Claim 검증과 추천 후보 정책

`ClaimEvidenceVerifier`는 검색 성공과 검증 성공을 구분한다.

| 판정 | 상품 정책 |
| --- | --- |
| `SUPPORTED` | `EVIDENCE_SUPPORTED`로 포함 |
| `INSUFFICIENT` | `CLAIM_ONLY`로 포함 |
| `CONTRADICTED` | 제외 |
| `UNSUPPORTED` | 보류 |
| `ERROR` | 보류 |

복합 성분 Claim은 조합 전체를 직접 다룬 `combination` 결과가 있고, 인용 Evidence의
`target_ids`가 전체 성분을 포함할 때만 `SUPPORTED`가 된다. 각 성분의 단독 Evidence가 모두
있어도 조합 효능이나 병용 안전성 근거로 승격하지 않는다.

`IngredientRecommendationSelector`는 Evidence-supported 후보를 Claim-only 후보보다 먼저
배치한다. Product 조회는 후보 성분별로 수행하며, 동일 상품은 `product_id` 기준으로 병합한다.
병합할 때 근거 등급별 성분 ID, statement ID와 Evidence ID를 중복 없이 보존한다.

## 5. 책임 클래스

| 파일·클래스 | 책임 |
| --- | --- |
| `agent/rag_route_policy.py::RagRoutePolicy` | LLM 제안 뒤의 결정적 RAG 경로 확정 |
| `agent/rag_workflow.py::RagWorkflowNodes` | Claim 검색·식별·검증·추천 후보 State 전이 |
| `agent/claim_verification.py::ClaimEvidenceVerifier` | Claim별 Evidence 무결성 및 지원 상태 판정 |
| `agent/claim_verification.py::IngredientRecommendationSelector` | 판정 상태를 상품 추천 근거 등급으로 변환 |
| `agent/rag_response.py::RagResponseAssembler` | Claim과 Evidence의 표현·인용 규칙 분리 |
| `agent/nodes.py::AgentNodes` | 상품 조회·병합, 루틴과 공통 상태 전이 |
| `agent/runtime.py::AgentRuntime` | 도구 호출 제한, 오류, 이벤트, 안정 ID 공통 정책 |
| `agent/citations.py::EvidenceCitationMapper` | Evidence 메타데이터만 Citation으로 변환 |

`AgentNodes`는 Evidence 검색과 판정 책임을 갖지 않는다. RAG 노드가 만든 구조화 상태를 사용해
Product 조회와 최종 후보 조립을 수행한다.

## 6. 응답 및 Citation 규칙

- Claim은 `유사 사용자 사례에서 발굴된 탐색 정보` 수준으로만 표시한다.
- Claim은 Citation을 생성하지 않는다.
- Citation은 실제 검색되고 Claim 지원 판정에 사용된 `EvidenceRecord` 메타데이터로만 만든다.
- `EVIDENCE_SUPPORTED` 상품은 Claim-only 상품보다 먼저 표시한다.
- `CLAIM_ONLY` 상품에는 현재 연결된 공인 근거로 Claim을 충분히 확인하지 못했다는 한계를 붙인다.
- 성분 Evidence를 완제품 자체의 임상 효과로 표현하지 않는다.
- Evidence 없음은 효과 없음이나 상반 근거로 해석하지 않는다.
- LLM이 생성한 출처 문자열은 Citation으로 사용하지 않는다.

## 7. BGE-M3 결정과 smoke fixture

운영 Agent 임베딩은 `BAAI/bge-m3`, 1,024차원으로 고정돼 있다.

- `ProductionAgentConfig`는 로컬 BGE-M3가 아닌 임베딩 설정을 거부한다.
- `ClaimRetriever.embedding_model`도 BGE-M3여야 운영 조립을 통과한다.
- 로컬 모델은 최초 사용 시 한 번 로드하고 같은 인스턴스를 재사용한다.

제공된 product smoke dump의 Claim/Evidence 벡터는 `text-embedding-3-small`, 1,536차원이다.
따라서 해당 dump는 데이터 관계와 Backend/Agent 어댑터 개발용 fixture이며 운영 BGE-M3 정합성의
통과 근거가 아니다. 실제 운영 연결 전 Backend/Data 파트에서 인덱스 모델·차원·재임베딩을
합의해야 한다.

이번 Agent 변경에는 DB 모델, Alembic, Backend, Data 구현이 포함되지 않는다.

## 8. 유지되는 공개 진입점

- `ChatService.handle_turn(ChatServiceRequest) -> ChatTurnOutput`
- `EvidencePipeline.run(EvidenceSearchRequest) -> EvidenceBundle`
- `ProductRepository`, `IngredientRepository`, `RoutinePlanner` 주입 구조
- Backend를 Agent에서 역방향 import하지 않는 의존성 방향

운영 조립에는 `ClaimRetriever` 주입이 필요하다. Backend 호출부는 Agent가 소유한
`ProductionAgentDependencies` 계약에 맞는 구현을 제공해야 한다.

## 9. 검증 결과

2026-09-17 현재 로컬 작업 트리 기준:

```text
uv run pytest tests/agent -q
116 passed

uv run pytest tests -q
186 passed

uv run ruff check agent tests/agent
All checks passed!

git diff --check
passed
```

검증 범위에는 LangGraph 분기, Claim/Evidence State 분리, Claim별 Evidence 판정, 복합 Claim
방어, Citation 제한, Claim-only 상품 포함, 근거별 정렬, 동일 상품 중복 제거, 후보 참조와 기존
Agent 회귀가 포함된다.

실제 Claim/Evidence DB 검색, PostgreSQL/pgvector 조회, 운영 BGE-M3 모델 로딩과 검색 품질은
Backend/Data 연결 후 별도 통합 테스트가 필요하다.

## 10. 브랜치 게시 전 확인

현재 로컬 변경을 의미 단위로 커밋한 뒤 다음 순서를 따른다.

1. `git fetch origin`으로 원격 상태를 갱신한다.
2. 현재 브랜치에서 최신 `origin/main`을 병합한다.
3. 충돌이 Agent 밖의 파일이나 공용 설정에서 발생하면 임의로 해결하지 않고 담당자와 합의한다.
4. Agent 및 전체 테스트를 다시 실행한다.
5. `feature/agent-two-layer-rag-main`을 push하고 main 대상 PR을 만든다.

PR은 GitHub 화면에서 `Squash and merge`로 병합한다.
