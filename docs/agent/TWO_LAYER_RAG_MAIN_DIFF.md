# 2-Layer RAG Agent — main 대비 변경점

## 1. 비교 기준

- 점검일: 2026-09-17
- 최신 원격 기준: `origin/main` `b6ef764`
- Agent 구현 커밋: `5066ee7` (`feat(agent): 2-layer RAG 노드와 Claim 검증 흐름`)
- 구현 브랜치: `feature/agent-two-layer-rag`
- 구현 기준 부모: `feature/rag-pipeline` `5147f9e`

로컬 `main`은 `d24d24f`로 `origin/main`보다 12커밋 뒤에 있으므로 비교 기준으로 사용하지
않는다. `feature/rag-pipeline`과 `origin/main` 사이에는 아직 main에 없는 Data·문서 변경
45개(5,990 additions)가 있다. 반면 `5066ee7` 자체의 변경은 Agent와 관련 테스트 23개
파일로 제한된다.

따라서 다음 두 작업을 구분해야 한다.

1. 로컬 통합 검증: `feature/rag-pipeline`을 Agent 구현 커밋으로 fast-forward한다.
2. Agent 전용 PR: 최신 `origin/main`에서 새 브랜치를 만들고 `5066ee7`과 이 문서 커밋만
   cherry-pick한다.

현재 `feature/agent-two-layer-rag`를 그대로 main 대상 PR로 올리면 부모 브랜치의 Data 변경도
PR에 포함되므로 사용하지 않는다.

## 2. LangGraph 흐름 변경

### 명시 성분 질문

```text
UNDERSTAND_REQUEST
  → RESOLVE_ENTITIES
  → ROUTE_TASK
  → ROUTE_RAG
  → SEARCH_EVIDENCE
  → ASSEMBLE_RAG_RESPONSE
  → VALIDATE_RESULT
```

예: `나이아신아마이드 효능과 주의를 알려줘`

- `rag_route=evidence_only`
- Claim 검색을 호출하지 않는다.
- 식별된 표준 성분 ID로 Evidence를 바로 검색한다.

### 피부 고민 기반 질문

```text
UNDERSTAND_REQUEST
  → ROUTE_TASK
  → ROUTE_RAG
  → SEARCH_CLAIMS
  → RESOLVE_CLAIM_INGREDIENTS
  → SEARCH_EVIDENCE
  → ASSEMBLE_RAG_RESPONSE
  → PROCESS_TASK(Product)
  → VALIDATE_RESULT
```

예: `피지가 많고 좁쌀 여드름이 나는데 세럼 추천해줘`

- `rag_route=claim_then_evidence`
- NIA Claim에서 후보 성분을 찾는다.
- Data가 `MATCHED`로 전달한 `ingredient_id`는 Agent에서 다시 문자열 매칭하지 않는다.
- ID가 미확정된 anchor만 `IngredientRepository`로 보완 식별한다.
- Evidence가 확인된 성분만 상품 검색 필터로 사용한다.
- Evidence가 없거나 Claim 검색이 실패하면 상품 추천을 중단한다.

## 3. State와 DTO 변경

`AgentState`에 다음 필드가 추가됐다.

| 필드 | 타입 | 역할 |
| --- | --- | --- |
| `rag_route` | `RagRoute` | `evidence_only`와 `claim_then_evidence` 분기 |
| `claim_bundle` | `ClaimBundle` | NIA 탐색 주장과 성분 anchor 보관 |
| `evidence_bundle` | `EvidenceBundle` | 공인 근거 검색·적용성·생성 결과 보관 |

Claim DTO는 `agent/rag/claim_schemas.py`에 별도로 정의했다. `ClaimHit`과
`EvidenceRecord` 사이에 상속이나 공용 결과 타입을 만들지 않았다. 이 분리로 NIA 사용자
경험담이 Evidence 인용으로 렌더링되는 경로를 차단한다.

Claim 계약의 주요 검증은 다음과 같다.

- `MATCHED` anchor에는 `ingredient_id`가 반드시 있어야 한다.
- 미확정 anchor에는 `ingredient_id`를 넣을 수 없다.
- `SUCCESS` 검색에는 최소 한 개의 hit이 있어야 한다.
- `ERROR` 검색에는 원인 메시지가 있어야 한다.
- Agent는 `APPROVED` Claim만 처리한다.
- 중복 `statement_id`는 계약 오류로 중단한다.

## 4. 신규 책임 클래스

| 파일·클래스 | 책임 |
| --- | --- |
| `agent/rag_workflow.py::RagWorkflowNodes` | Claim 검색, 성분 ID 확정, Evidence 검색 노드 |
| `agent/rag_response.py::RagResponseAssembler` | Claim과 Evidence를 다른 표현·인용 규칙으로 조립 |
| `agent/runtime.py::AgentRuntime` | 도구 호출 제한, 오류, 이벤트, 안정 ID 공통 정책 |
| `agent/task_planning.py::TaskPlanBuilder` | Claim 검증을 상품 검색보다 먼저 배치 |
| `agent/citations.py::EvidenceCitationMapper` | Evidence 메타데이터만 Citation으로 변환 |

기존 `AgentNodes`에서 Evidence 검색·생성·인용 책임을 제거했다. `AgentNodes`는 일반 대화,
상품, 루틴과 공통 상태 전이에 집중한다.

기존 `ClaimGenerator`는 새 Claim Layer의 검색기와 이름이 충돌했다. 실제 책임에 맞춰 다음과
같이 변경했다.

| main 이름 | 변경 이름 |
| --- | --- |
| `ClaimGenerator` | `EvidenceStatementGenerator` |
| `ClaimGenerationRequest` | `EvidenceStatementGenerationRequest` |
| `GeneratedClaim` | `GeneratedEvidenceStatement` |
| `openai_generator.py` | `evidence_statement_generator.py` |

직렬화되는 문장·출처 필드의 의미는 유지하지만 Python import 경로와 클래스명은 변경되므로
외부 호출자가 이전 이름을 import한다면 수정이 필요하다.

## 5. BGE-M3 결정 반영

운영 Agent의 임베딩 모델은 `BAAI/bge-m3`로 고정했다.

- `ProductionAgentConfig`는 `EmbeddingProvider.LOCAL`이 아니면 검증 오류를 낸다.
- Local embedding model은 `LocalEmbeddingModel.BGE_M3`이어야 한다.
- `ClaimRetriever.embedding_model`도 `BAAI/bge-m3`이어야 운영 조립을 통과한다.
- BGE-M3 출력 차원은 기존 Agent 정의대로 1,024차원이다.

현재 main의 `Backend AgentConfigurationAssembler`는 OpenAI 1,536차원 설정을 만들 수 있으므로
그 설정은 새 `ProductionAgentConfig`에서 거부된다. 실제 운영 연결 전 Backend/Data 파트에서
다음 작업이 필요하다.

1. 질의·적재 설정을 모두 BGE-M3로 통일한다.
2. 실제 `claim_chunk`를 조회하는 `ClaimRetriever` 구현을 주입한다.
3. Claim과 Evidence 인덱스가 모두 1,024차원 BGE-M3 벡터인지 검증한다.
4. 기존 1,536차원 Evidence 저장 구조의 ERD·마이그레이션·재임베딩을 합의한다.

이번 Agent 변경에는 DB 모델, Alembic, Backend, Data 구현이 포함되지 않는다.

## 6. 응답 및 Citation 규칙

- Claim은 `유사한 사용자 사례의 탐색적 주장`으로만 표시한다.
- Claim은 Citation을 생성하지 않는다.
- Citation은 검색된 `EvidenceRecord`의 메타데이터로만 만든다.
- Evidence 검색이 실패하면 Claim을 검증된 효능처럼 확정하지 않는다.
- Evidence가 없으면 Claim 기반 상품 추천을 수행하지 않는다.
- LLM이 생성한 출처 문자열은 Citation으로 사용하지 않는다.

## 7. main에서 유지되는 공개 진입점

다음 공개 진입점은 유지된다.

- `ChatService.handle_turn(ChatServiceRequest) -> ChatTurnOutput`
- `EvidencePipeline.run(EvidenceSearchRequest) -> EvidenceBundle`
- `ProductRepository`, `IngredientRepository`, `RoutinePlanner` 주입 구조
- Backend를 Agent에서 역방향 import하지 않는 의존성 방향

운영 조립에는 신규 `ClaimRetriever` 주입이 필수가 됐다. Backend 호출부가
`ProductionAgentDependencies`를 만들 때 이 필드를 추가해야 한다.

## 8. 검증 결과

핵심 2-Layer 시나리오:

```text
test_concern_query_runs_claim_then_evidence_then_product       PASSED
test_explicit_ingredient_skips_claim_search                    PASSED
test_claim_is_exploratory_when_evidence_has_no_results         PASSED
test_claim_failure_stops_evidence_and_product_search           PASSED
```

전체 Agent 및 관련 RAG 회귀 테스트:

```text
121 passed
ruff: All checks passed
```

검증 범위에는 LangGraph 분기, Claim/Evidence State 분리, ID 전달, Citation 제한, 실패 중단,
기존 Agent 회귀가 포함된다. 실제 `claim_chunk`, PostgreSQL/pgvector, 운영 BGE-M3 모델 로딩과
검색 품질은 Backend/Data 연결 후 별도 통합 테스트가 필요하다.

## 9. 별도 Agent 브랜치 게시 절차

`feature/rag-pipeline`이 main에 합쳐지기 전에 Agent 변경을 별도 PR로 올려야 한다면 최신
main에서 깨끗한 브랜치를 만든다.

```bash
git fetch origin
git switch -c feature/agent-two-layer-rag-main origin/main
git cherry-pick 5066ee7
# 이어서 이 문서를 추가한 docs 커밋도 cherry-pick한다.
```

PR 전에는 새 브랜치에서 최신 `origin/main`을 반영하고 Agent 전체 테스트를 다시 실행한다.
충돌이 Agent 밖의 파일이나 공용 설정에서 발생하면 임의로 해결하지 않고 파트 담당자와
합의한다.
