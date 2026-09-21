# NIA Case 런타임 Claim 추출 구현 계획

> 작성: 2026-09-21 02:19 KST
>
> 상태: 핵심 코드·LangGraph·DB 검색 구현 완료, 골든 셋·외부 LLM E2E 확인 대기
>
> 구현 갱신: 2026-09-21 10:20 KST
>
> 범위: NIA Case 검색 → 런타임 Claim 추출 → 룰 검증 → Ingredient/Evidence/Product 연결

## 1. 최종 결정

피부 고민형 질의의 기본 경로에서 전체 3,581건 offline Claim annotation과 Claim 벡터 검색을
제외한다. 유사 Case Top-3만 런타임 LLM에 전달하고, 사용자 질문과 관련된 성분 Claim을 원문
구속 구조화 출력으로 추출한다.

```text
사용자 피부 고민
  → BGE-M3 Case 후보 검색
  → BGE reranker Top-3
  → 런타임 LLM Claim 추출
  → exact quote·성분명 룰 검증
  → canonical Ingredient Resolution
  → 성분별 Evidence 검증
  → confirmed 성분 상품 검색
  → Claim/Evidence 상태를 분리한 답변
```

명시적인 성분 질의는 Case와 런타임 Claim 추출을 건너뛴다.

```text
명시적인 성분 질의
  → Ingredient Resolution
  → Evidence RAG
  → Product
  → Answer
```

## 2. 왜 이 구조로 바꾸는가

실제 Case 3,581건의 `page_content` 길이를 확인한 결과는 다음과 같다.

| 항목 | 문자 수 |
| --- | ---: |
| Case 평균 | 약 1,859자 |
| Case 중앙값 | 1,849자 |
| Case 상위 95% | 2,405자 |
| 중앙값 Top-3 합계 | 5,547자 |
| 상위 95% Top-3 합계 | 7,215자 |
| 가장 긴 Case | 3,324자 |

Top-3는 런타임 모델 문맥에 넣을 수 있는 규모다. 현재 production Claim annotation은
0/3,581건이므로, 전체 선처리를 P3 선행 조건으로 두는 것보다 실제 선택된 세 사례만 처리하는
편이 현재 개발·검증 단계에 적합하다.

단, 요청마다 구조화 LLM 호출이 한 번 추가된다. 운영 사용량이 커져 지연·비용이 문제가 되면
보존한 offline annotation/Claim embedding 경로를 후속 최적화로 다시 비교한다.

## 3. LLM과 규칙 계층의 책임

### 런타임 LLM이 하는 일

- 사용자 질문과 Top-3 Case를 함께 읽는다.
- 질문과 관련된 성분 효능 Claim만 선택한다.
- 원문 `case_id`, 성분 raw name, exact source quote를 구조화해 반환한다.
- 독립 효능은 성분별 단일 Claim으로 나눈다.
- 공동 효과가 원문에 명시된 경우에만 조합 Claim을 반환한다.

### 런타임 LLM이 하지 않는 일

- `ingredient_id` 생성 또는 선택
- 원문에 없는 성분·효능 보충
- 과학적 근거·검수 상태 판정
- 상품 추천 가능 여부 판정
- NIA의 `evidence_sources`를 공식 Citation으로 승격
- 개별 성분 Evidence로 조합 Claim 지원 판정

### 코드가 결정적으로 검증하는 일

1. 반환된 `case_id`가 실제 Top-3에 있는지 확인
2. `source_quote`가 해당 Case 원문에 정확히 있는지 확인
3. 모든 raw 성분명이 quote에 실제로 있는지 확인
4. 단일 Claim은 성분 1개, 조합 Claim은 성분 2개 이상인지 확인
5. 중복 Claim 제거
6. 기존 Ingredient Repository로 canonical ID 조회
7. unresolved·ambiguous 성분은 ID를 추측하지 않고 Evidence/Product에서 제외

## 4. 구조화 출력 계약

Agent가 소유할 최소 타입은 다음과 같다.

```python
class CaseClaimType(StrEnum):
    INGREDIENT_EFFECT = "ingredient_effect"
    COMBINATION_EFFECT = "combination_effect"


class ExtractedIngredientMention(RagModel):
    raw_name: str


class ExtractedCaseClaim(RagModel):
    case_id: str
    claim_type: CaseClaimType
    ingredients: list[ExtractedIngredientMention]
    source_quote: str


class CaseClaimExtractionRequest(RagModel):
    query: str
    cases: list[CaseSearchHit]
    limit: int


class CaseClaimExtractionResult(RagModel):
    status: LookupStatus
    claims: list[ExtractedCaseClaim]
    model: str | None
    prompt_version: str
    error_message: str | None
```

자유로운 `summary`, `claimed_effect`, `relevance_reason` 필드를 받지 않는다. 원문보다 강한 의미를
LLM이 새로 쓰는 경로를 막기 위해 Evidence query와 Claim 표시는 exact quote를 기준으로 한다.

## 5. 런타임 모델 사용 방식

Claim 추출기는 Agent의 기존 `ChatModelConfig`를 사용한다.

- `provider=openai`: 사용자 요청마다 설정된 OpenAI 모델 API를 호출한다.
- `provider=local` 또는 `ollama`: 설정된 로컬 OpenAI 호환 서버를 호출한다.
- 일반 ChatGPT/Codex 대화창 모델을 실행 중인 애플리케이션이 직접 호출할 수는 없다.

따라서 이 구조는 전체 3,581건 annotation API 호출을 없애지만, `provider=openai` 운영에서는
실제 사용자 요청마다 Top-3 Claim 추출 API 호출이 발생한다.

## 6. LangGraph 목표 구조

피부 고민형 노드는 다음 순서로 구성한다.

```text
embed_case_query
  → search_cases
  → rerank_cases
  → extract_case_claims
  → validate_case_claims
  → resolve_claim_ingredients
  → verify_claims
  → build_recommendation_candidates
  → search_products
  → assemble_rag_response
```

- 기존 호출 호환을 위해 `RagRoute.CLAIM_THEN_EVIDENCE` Enum 값은 유지하되, 운영 기본 연결은
  `search_cases`에서 시작하는 Case 경로로 변경한다.
- Case, 런타임 Claim, Evidence는 각각 별도 Bundle/State로 유지한다.
- LLM 추출 실패를 Evidence 부족으로 바꾸지 않는다.
- NIA Claim은 체감·탐색 정보로 표시하고 공식 Citation으로 렌더링하지 않는다.
- Evidence가 없거나 미검수여도 canonical ID가 확정된 Claim 성분의 상품 후보는 유지한다.

## 7. 구현 단계

### P3-1. 계약 문서

- [x] `docs/contracts/backend-to-agent.md` 10절을 런타임 Claim 추출 계약으로 교체
- [x] offline annotation을 P3 필수 경로에서 제외
- [x] Case/Claim/Evidence 역할과 실패 상태 분리

### P3-2. Agent Case 검색 DTO·포트

상태: **완료**

예상 파일:

- `agent/rag/case_schemas.py` 신규
- `agent/rag/ports.py`

작업:

- `CaseSearchRequest/Hit/Result`
- `CaseRerankRequest/Result`
- `CaseRetriever`, `CaseReranker`
- SUCCESS/NO_RESULTS/UNSUPPORTED/ERROR 불변조건

### P3-3. Agent 런타임 Claim 추출

상태: **완료**

예상 파일:

- `agent/rag/case_claim_schemas.py` 신규
- `agent/rag/case_claim_extractor.py` 신규
- `agent/rag/case_claim_validator.py` 신규
- `agent/rag/ports.py`
- `agent/prompts.py`
- `agent/factory.py`

작업:

- `CaseClaimExtractor` 구조화 출력 포트와 채팅 모델 구현
- 원문을 데이터로만 취급하는 prompt injection 방어 문구
- exact quote 기반 최소 출력
- validator에서 Case ID·quote·성분명·Claim shape 검증
- 모델명·`prompt_version` 기록

### P3-4. Ingredient/Evidence 연결

상태: **완료**

예상 파일:

- `agent/rag/case_claim_anchor_adapter.py` 신규
- `agent/rag/schemas.py`
- `agent/rag_workflow.py`
- `agent/claim_verification.py`

작업:

- raw name을 기존 `IngredientRepository.resolve()`로 조회
- `EvidenceQueryOrigin.CASE_CLAIM` 추가
- exact quote와 확정 성분 ID로 Evidence anchor 생성
- 조합 Claim은 모든 성분 매칭 시에만 `MULTI + ALL`로 검증
- 동일 성분을 여러 Case에서 얻으면 성분 후보는 병합하고 Case provenance는 보존

### P3-5. Backend Case 검색

상태: **완료**

예상 파일:

- `backend/repositories/nia_case_document_repository.py`
- `backend/services/two_layer_rag_adapters.py`

작업:

- 3,581건 BGE-M3 Case vector 검색
- text/embedding version과 1,024차원 검증
- Case 후보 DTO 변환
- Case reranker에 전달할 1차 후보 반환

Backend는 런타임 Claim을 생성하거나 검증하지 않는다. 기존 Claim DB 검색기는 이번 기본 경로에서
호출하지 않는다.

### P3-6. LangGraph 라우팅

상태: **완료**

예상 파일:

- `agent/schemas.py`
- `agent/rag_route_policy.py`
- `agent/nodes.py`
- `agent/graph.py`
- `agent/rag_workflow.py`

작업:

- Case 검색·rerank·추출·검증 노드 추가
- 피부 고민형 `CASE_THEN_EVIDENCE` 경로 연결
- 명시 성분형 Evidence 직행 경로 보존
- 단계별 오류와 보류 사유를 State/compact debug에 노출

### P3-7. 테스트

1. 피부 고민 → Case 후보 → rerank Top-3
2. LLM이 Top-3 밖의 `case_id`를 반환하면 제외
3. 원문에 없는 quote 또는 성분명을 반환하면 제외
4. 한 Case의 여러 성분 중 질문 관련 Claim만 채택
5. 독립 Claim과 명시적 조합 Claim 분리
6. 조합 일부 성분만 매칭됐을 때 단일 Claim으로 축소하지 않음
7. unresolved·ambiguous 성분의 Evidence/Product 차단
8. 동일 성분·동일 상품 중복 제거와 provenance 보존
9. Evidence 없음/미검수 Claim-only 상품 유지
10. 명시 성분 질의의 Case/Claim 추출 생략
11. LLM 오류·Case 없음·reranker fallback
12. 실제 통합 DB Case → 런타임 Claim → Evidence → Product smoke

현재 1, 2, 3, 5, 6, 9, 10, 11, 12와 unresolved 성분 차단의 결정적 테스트를 구현했다. 실제 DB
Case 벡터 조회와 외부 LLM을 포함한 E2E도 통과했다. 4, ambiguous 분기, 8의 다중 Case
provenance 세부 회귀는 후속 테스트로 남아 있다.

## 8. Offline annotation 경로 처리

기존에 구현한 다음 코드는 삭제하지 않는다.

- annotation corpus/provenance/manifest exporter
- production annotation dry-run·resume·승인 안전장치
- annotation → Claim export
- Claim BGE-M3 적재 Service/Repository
- 관련 단위 테스트

다만 현재 P3 완료 조건에서는 다음을 실행하지 않는다.

- OpenAI 5건 production annotation
- 전체 3,581건 production annotation
- production Claim export·embedding·DB 적재

현재 완료 건수는 0/3,581건이다. 향후 런타임 Claim 추출의 비용·지연·재현성이 문제가 되거나
골든 셋에서 offline 방식이 더 우수한지 비교할 때 후속 최적화로 사용한다.

## 9. 구현 전 준비 상태

- [x] Case 3,581건 BGE-M3 1,024차원 적재
- [x] 실제 Case 길이 분포 확인
- [x] Backend ↔ Agent 런타임 추출 계약 갱신
- [x] offline annotation 경로 보존·보류 결정
- [x] Agent DTO·포트 구현
- [x] Backend Case Retriever 구현
- [x] 구조화 Claim extractor·validator 구현
- [x] LangGraph 경로 연결
- [x] 단위·Agent·DB 검색 통합 테스트
- [ ] 골든 셋 작성 및 prompt/version 평가

## 10. 구현 및 검증 결과 — 2026-09-21 10:20 KST

- Case 검색: 기존 `nia_case_document`에서 BGE-M3 1,024차원 cosine 후보 20건 조회
- Case rerank: `BAAI/bge-reranker-v2-m3`로 Top-3 선정
- 런타임 추출: `case_id`, raw 성분명, exact quote, 단일/조합 유형만 구조화 출력
- 모델 입력 최소화: `query`, `case_id`, `page_content`, `limit`만 전송하고 메타데이터·원본 파일
  provenance는 제외
- 규칙 검증: Top-3 Case ID, exact quote, quote 내 성분명, 중복 차단
- 성분 연결: 기존 `IngredientRepository`와 alias fallback 사용
- 조합 방어: 모든 성분이 매칭된 조합만 `MULTI + ALL` Evidence anchor로 변환
- 상품 정책: Evidence 0건이어도 `INSUFFICIENT → CLAIM_ONLY` 성분 상품 후보 유지
- 명시 성분 정책: Case 검색·rerank·Claim 추출을 건너뛰고 Evidence 직행
- 최적화: Case와 Evidence reranker가 하나의 CrossEncoder 모델 인스턴스를 공유
- 호환 경로: offline `ClaimRetriever`는 명시적으로 주입한 비교·개발 실행에서만 사용

검증 결과:

```text
전체 기본 테스트: 449 passed, 3 deselected
Agent + Case 검색 단위 테스트: 149 passed
실제 PostgreSQL NIA Case 벡터 검색: 1 passed
```

실제 OpenAI 포함 전체 CLI는 사용자에게 Top-3 NIA 원문 전송 범위를 알리고 명시적 승인을 받은
뒤 실행했다. `피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?` 질의에서 Case Claim으로
나이아신아마이드와 BHA를 추출했고, 검수 완료 Evidence가 없어도 나이아신아마이드 상품 후보를
`Claim 기반·근거 미확인`으로 유지했다. `partial`은 실행 실패가 아니라 검수 완료 Evidence가
없다는 상태 표현이다.

추가로 확인된 품질 과제:

- `BHA`는 표준 성분으로 연결되지 않아 Ingredient Resolution alias 정책이 필요하다.
- BHA, 티트리 오일, 나이아신아마이드가 함께 언급된 문장을 성분별 Claim으로 분리하지 못했다.
- 상품 후보에 어떤 Claim 성분으로 연결됐는지 표시하지 않아 관련성을 파악하기 어렵다.

## 10.1 세 Intent 품질 회귀 점검 — 2026-09-21 13:39 KST

`tests/agent/test_three_intent_quality_scenarios.py`에 다음 9개 대표 시나리오를 추가했다.

- `product_discovery`: 고민 기반 Case RAG, 제형·사용감 필터, 명시 성분 제품 탐색
- `evidence_qa`: 단일 성분 효능, 주의사항, 두 성분 병용
- `routine_planning`: 제품 미지정 확인 질문, 명시 제품 루틴, 기존 루틴 수정

각 시나리오는 Intent만 확인하지 않고 최종 상태와 상품 후보·Citation·Routine·확인 질문까지
검증한다.

```text
신규 품질 테스트: 9 passed, 1 xfailed
Agent 전체 테스트: 154 passed, 1 xfailed
Ruff: passed
```

초기 `xfail`은 고민형 문장을 개발용 해석기가 `clarification`으로 반환했을 때 결정 규칙이
`product_discovery`를 추가하면서 기존 `clarification`을 제거하지 않는 결함이었다. 이 경우 정보
확인 단계가 먼저 실행되어 Case RAG가 중단됐다. 실제 OpenAI E2E에서는 해당 질의가
`product_discovery`로 정상 분류됐지만 LLM 오분류 방어가 필요했다.

## 10.2 고민형 상품 탐색 Intent 방어 보강 — 2026-09-21 13:44 KST

`RagRoutePolicy`가 고민형 상품 탐색을 결정적으로 확정하면 상충하는 `clarification`과
`evidence_qa`를 제거한 뒤 `product_discovery`만 남기도록 수정했다. 이에 따라 기존 `xfail`을
정상 기대값으로 전환했다.

```text
대상 시나리오: product-concern-case-rag
결과: 1 passed, 9 deselected
```

이번 수정에서는 요청에 따라 전체 테스트를 다시 실행하지 않았다.

## 11. 완료 조건

- Top-3 Case 원문 밖의 성분·Claim이 Evidence/Product 단계로 넘어가지 않는다.
- LLM이 canonical ingredient ID나 Evidence 상태를 결정하지 않는다.
- 원문 exact quote와 Case provenance를 재현할 수 있다.
- 명시 성분형과 피부 고민형 경로가 분리된다.
- Evidence가 없는 Claim-only 상품 정책을 유지한다.
- 전체 offline annotation 없이 실제 통합 DB smoke가 동작한다.
- 런타임 모델·prompt version과 단계별 실패 상태가 관측 가능하다.
