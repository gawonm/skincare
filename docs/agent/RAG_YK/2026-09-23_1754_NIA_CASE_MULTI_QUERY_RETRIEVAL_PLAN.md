# NIA Case 복수 질의 검색·전용 리랭크·Recall@20 평가 계획

> 작성: 2026-09-23 17:54 KST
>
> 상태: **구현 전 계획**
>
> 범위: **Agent 파트만** — 복수 임베딩 질의와 RRF 융합, BGE 리랭크 전용 질의,
> 실제 DB 기준 Recall@20 평가

## 1. 결정 사항

다음 세 방향을 우선 구현한다.

1. 하나의 Case 의도에서 복수의 임베딩 검색 질의를 결정적으로 생성하고, 질의별 검색 결과를
   RRF(Reciprocal Rank Fusion)로 합친다.
2. 임베딩 검색 질의와 BGE 리랭크 질의를 분리한다. 동일한 문자열을 재사용하지 않고 동일한
   구조화 의도에서 단계별 표현을 만든다.
3. 실제 NIA Case DB에서 1차 검색 Recall@20을 측정한다. 리랭커 품질과 분리해 후보 회수 실패를
   먼저 확인한다.

이번 단계에서는 Backend 검색 계약, DB 스키마, 적재 데이터의 `embedding_text`, 설정 파일을
변경하지 않는다. `nia_case_text/v2` 재임베딩은 이번 평가에서 복수 질의만으로 회수율이 충분히
개선되지 않을 때 별도 계획으로 판단한다.

## 2. 현재 문제

현재 예시 Case 질의는 다음과 같다.

```text
30살 여성 겨울 민감성 건조 피부 관련 성분 및 주의사항
```

이 질의는 사용자 조건을 보존하지만 다음 문제가 있다.

- `30살`, `여성`, `겨울`, `민감성`, `건조`가 하나의 평면 문자열에 섞여 각 조건의 역할이
  구분되지 않는다.
- `건조`와 연관된 보습·수분 부족 문맥, `민감`과 연관된 진정·자극 주의 문맥이 Case 문서의
  표현과 다르면 1차 검색에서 놓칠 수 있다.
- 짧은 질의를 `질문 + 답변 + 추론` 전체로 구성된 긴 Case 임베딩과 비교하므로 질의와 문서의
  표현 단위가 비대칭이다.
- Case 검색, BGE rerank, Top-3 관련 성분 선별이 같은 `case_query` 문자열을 사용한다. 일관성은
  있지만 각 단계의 recall·precision 목적 차이를 반영하지 못한다.
- 현재 후보 상한은 Top-20이다. 필요한 Case가 여기에 없으면 reranker는 복구할 수 없다.

따라서 목표는 질의를 무조건 길게 만드는 것이 아니라, 사용자에게서 확인된 하나의 의도를
여러 검색 관점으로 표현하고 후보를 합치는 것이다.

## 3. 목표와 제외 범위

### 3.1 목표

- 사용자가 명시한 연령·성별·계절·피부 타입·피부 상태·피부 고민을 잃지 않는다.
- 사용자가 말하지 않은 증상이나 질환은 검색 확장 과정에서 만들지 않는다.
- 서로 다른 표현의 Case를 복수 질의로 회수하되 최종 rerank 입력 후보 수는 현재 Top-20으로
  유지한다.
- reranker에는 유사 Case 판단 기준이 드러나는 자연어 질의를 제공한다.
- Claim 관련 성분 선별에는 확장 표현이 아닌 기존 canonical `case_query`를 사용한다.
- 실제 DB 평가에서 1차 검색과 최종 Top-3 성능을 분리해 기록한다.

### 3.2 이번 범위에서 하지 않는 것

- `backend/`, `models/`, `migrations/`, `data/scripts/` 변경
- `config.yaml` 및 샘플 설정 변경
- `embedding_text` 재생성 또는 `nia_case_text/v2` 적재
- BM25, SQL 메타데이터 가중치, 새 인덱스 추가
- 새 라이브러리 추가
- 연령·성별·피부 타입의 hard filter 적용
- 사용자가 말하지 않은 `홍조`, `가려움`, `아토피`, 특정 질환을 LLM으로 추론해 질의에 추가

## 4. 핵심 설계

### 4.1 동일 문자열이 아니라 동일 의도를 공유한다

```text
원문 사용자 요청
  → IntentQueryPlanner가 canonical Case 의도 확정
  → Case retrieval query 2~3개 생성
  → 질의들을 한 번에 BGE-M3 임베딩
  → 질의별 NIA Case Top-20 검색
  → case_id 기준 중복 제거 + RRF
  → 융합 Top-20
  → 상세한 Case rerank query로 BGE Top-3
  → canonical case_query로 Top-3 관련 성분 선별
```

단계별 질의의 출처는 하나이며 역할만 다르다.

| 필드 | 소비 단계 | 목적 |
| --- | --- | --- |
| `case_query` | Top-3 관련 성분 선별 | 사용자가 실제로 요청한 Case 주제를 간결하게 보존 |
| `case_retrieval_queries` | BGE-M3 벡터 검색 | 서로 다른 Case 표현을 넓게 회수 |
| `case_rerank_query` | BGE cross-encoder | 후보 전체 문맥을 읽고 유사도를 정밀 판단 |

### 4.2 질의 타입

고정된 질의 종류는 문자열 리터럴 대신 `StrEnum`으로 정의한다.

```python
class CaseRetrievalQueryKind(StrEnum):
    PROFILE = "profile"
    CONCERN = "concern"
    NATURAL_QUESTION = "natural_question"
```

각 질의는 Pydantic 모델로 전달한다.

```python
class CaseRetrievalQuery(AgentModel):
    kind: CaseRetrievalQueryKind
    text: str = Field(min_length=1)
```

`IntentQueryPlan`은 기존 `case_query`를 유지하면서 다음 필드를 추가한다.

```python
class IntentQueryPlan(AgentModel):
    case_query: str | None = Field(default=None, min_length=1)
    case_retrieval_queries: list[CaseRetrievalQuery] = Field(default_factory=list)
    case_rerank_query: str | None = Field(default=None, min_length=1)
    evidence_query: str | None = Field(default=None, min_length=1)
    product_query: str | None = Field(default=None, min_length=1)
    routine_query: str | None = Field(default=None, min_length=1)
```

기존 호출자가 `case_retrieval_queries`를 제공하지 않는 경우 `case_query` 하나를 검색 질의로 쓰는
fallback을 둔다. 이로써 기존 fixture와 개발용 adapter가 즉시 깨지지 않게 한다.

### 4.3 결정적 질의 생성

질의 변형은 LLM에 자유 생성시키지 않는다. `IntentQueryPlanner`가 원문에서 확정한 문맥과
허용된 도메인 확장만으로 만든다.

예시 입력:

```text
30살 여성 겨울 민감성 건조 피부 관련 성분 및 주의사항
```

예상 검색 질의:

```text
[PROFILE]
30살 여성 겨울철 건성 피부와 민감한 피부 상태에 적합한 성분 및 주의사항

[CONCERN]
겨울철 건조하고 자극받기 쉬운 피부의 보습·진정 성분과 사용 시 주의사항

[NATURAL_QUESTION]
겨울이 되면 피부가 건조하고 민감해지는 30대 여성에게 어떤 성분이 좋으며 무엇을 주의해야 하나
```

확장 규칙은 whitelist로 제한한다.

| 원문 신호 | 허용 확장 | 허용하지 않는 확장 예 |
| --- | --- | --- |
| `건조`, `건성` | `보습`, `수분 부족` | `아토피`, `각질 질환` |
| `민감`, `민감성` | `진정`, `자극 주의` | `알레르기`, `홍조` |
| `겨울` | `겨울철` | 원문에 없는 생활환경·질환 |

확장어는 의미 있는 이름을 가진 Enum 또는 클래스 상수로 관리한다. 같은 의미의 질의가 중복되면
정규화한 문자열 기준으로 제거하고, 결과적으로 하나만 남아도 오류로 처리하지 않는다.

`민감성 건조 피부`는 가능한 경우 다음처럼 구분한다.

- 피부 타입: `건성`
- 피부 상태: `민감`

현재 입력 계약에 피부 상태 전용 필드가 없으므로 이번 구현에서는 질의 생성 내부의 구분으로만
사용한다. 공용 사용자 프로필 계약이나 DB 메타데이터는 변경하지 않는다.

### 4.4 임베딩과 검색

- 모든 검색 질의는 `EmbeddingRequest.texts`에 넣어 한 번의 BGE-M3 batch 호출로 임베딩한다.
- 반환 벡터 수가 질의 수와 같은지 검증한다.
- 모든 벡터가 BGE-M3의 1,024차원인지 검증한다.
- 각 질의 벡터로 기존 `CaseRetriever.search`를 호출한다.
- 각 검색의 `candidate_limit`은 기존 기본값인 20을 유지한다.
- 성공한 결과를 RRF로 융합한 뒤 상위 20건만 reranker에 전달한다.

질의 수, 질의별 후보 수, 최종 후보 수는 숫자를 코드 곳곳에 직접 쓰지 않고 이름 있는 상수로
둔다. 이번 단계에서는 새 설정 키를 만들지 않는다. 실제 평가 후 운영 튜닝이 필요하면 공용
`config.yaml` 변경 승인을 별도로 받는다.

### 4.5 RRF 융합

벡터 cosine similarity는 질의마다 분포가 다를 수 있으므로 raw score 평균 대신 순위 기반 RRF를
사용한다.

```text
RRF(case) = Σ 1 / (RRF_RANK_CONSTANT + rank_in_query)
```

규칙:

1. 같은 `case_id`가 여러 질의에 나오면 RRF 점수를 합산한다.
2. 최종 정렬은 RRF 점수 내림차순이다.
3. RRF 동점이면 해당 Case가 받은 최대 `vector_similarity` 내림차순을 사용한다.
4. 그래도 같으면 `case_id` 오름차순으로 정렬해 결과를 결정적으로 만든다.
5. `page_content`, metadata, provenance는 원본 `CaseSearchHit`에서 그대로 보존한다.

`RRF_RANK_CONSTANT`의 초기값은 이름 있는 상수로 두되, 최종값은 3단계 실제 DB 평가 결과로
확정한다. 값 변경에 따른 Recall@20 차이를 평가 보고서에 남긴다.

### 4.6 일부 질의 실패 처리

- 임베딩 batch 자체가 실패하거나 모델·차원이 맞지 않으면 전체 Case 검색을 실패 처리한다.
- 개별 Case 검색이 실패했지만 성공한 검색이 하나 이상이면 성공 결과만 융합하고 degraded
  failure를 trace에 남긴다.
- 모든 검색이 `NO_RESULTS`이면 최종 결과도 `NO_RESULTS`이다.
- 모든 검색이 실패하면 최종 결과는 `ERROR`이며 각 실패 질의를 식별할 수 있는 메시지를 남긴다.
- 오류를 숨기거나 빈 `except`로 넘기지 않는다.

### 4.7 리랭크 전용 질의

리랭크 질의는 키워드 나열이 아니라 후보 선택 기준이 드러나는 자연어로 만든다.

```text
30세 여성의 겨울철 건성 피부이며 자극에 민감한 상태와 유사한 사례를 찾는다.
보습 또는 진정에 도움이 되는 성분과 자극·사용 시 주의사항을 구체적으로 설명한 사례를 우선한다.
```

규칙:

- 사용자 원문에 있는 연령·성별·계절·피부 타입·피부 상태를 보존한다.
- 피부 고민 일치가 연령·성별 일치보다 우선되도록 문장 순서를 구성한다.
- 연령·성별을 hard filter로 쓰지 않는다.
- 상품 추천, 루틴 기간, 제품 번호 등의 지시는 포함하지 않는다.
- `rerank_cases`만 `case_rerank_query`를 사용한다.
- `extract_case_claims`는 계속 canonical `case_query`를 사용한다.
- reranker 실패 fallback은 단일 벡터 순위가 아니라 RRF 융합 순위의 Top-3을 사용한다.

## 5. 구현 구조

### 5.1 수정 예정 파일

| 파일 | 변경 내용 |
| --- | --- |
| `agent/schemas.py` | `CaseRetrievalQueryKind`, `CaseRetrievalQuery`, 단계별 Case 질의 필드 추가 |
| `agent/query_planning.py` | 확정 문맥 기반 검색 질의 변형과 rerank 질의 생성 |
| `agent/rag_workflow.py` | batch 임베딩, 질의별 검색, RRF 융합 결과 사용, rerank 질의 분리 |
| `tests/agent/test_query_planning.py` | 변형 질의·허용 확장·금지 확장·중복 제거 검증 |
| `tests/agent/test_case_two_layer_rag_workflow.py` | 복수 검색·융합·부분 실패·단계별 질의 사용 검증 |
| `tests/agent/interactive_two_layer_rag_cli.py` | 질의별 검색 결과와 융합 Top-20을 구분해 출력 |

### 5.2 새 파일 예정

| 파일 | 역할 |
| --- | --- |
| `agent/rag/retrieval/case_result_fusion.py` | Pydantic 요청·결과를 받는 결정적 RRF 융합 클래스 |
| `tests/agent/test_case_result_fusion.py` | 중복 Case, 동점, 빈 결과, 부분 결과 융합 단위 테스트 |
| `tests/agent/case_retrieval_recall_eval.py` | 실제 DB에서 baseline과 변경안을 비교하는 수동 평가 진입점 |

새 폴더는 만들지 않는다.

### 5.3 변경하지 않는 파일

- `backend/services/two_layer_rag_adapters.py`
- `backend/repositories/nia_case_document_repository.py`
- `models/nia_case_document.py`
- `config.yaml`
- `data/processed/nia_case_documents_10s_30s.jsonl`

Backend에는 기존 `CaseSearchRequest`를 질의 수만큼 그대로 호출한다. Agent가 Backend의 새 응답
필드나 새 SQL을 요구하지 않으므로 이번 작업에는 파트 경계 계약 변경이 없다.

## 6. Recall@20 평가 계획

### 6.1 평가 목적

리랭커가 잘못 골랐는지와 필요한 Case가 애초에 후보에 없었는지를 분리한다.

- 1차 검색: `Hit@20`, `Recall@20`
- 최종 rerank: `MRR@3`, `nDCG@3`
- 조건 진단: 피부 고민, 피부 타입/상태, 계절, 연령대, 성별 일치율
- 운영 진단: 임베딩 시간, DB 검색 시간, rerank 입력 후보 수

### 6.2 비교군

| 실험 | 검색 방식 | rerank 질의 |
| --- | --- | --- |
| A: baseline | 현재 단일 `case_query` Top-20 | 현재 `case_query` |
| B: query-only | 복수 질의 + RRF Top-20 | 현재 `case_query` |
| C: full | 복수 질의 + RRF Top-20 | 전용 `case_rerank_query` |

B와 C를 분리해 1차 회수 개선과 rerank 개선을 각각 확인한다.

### 6.3 골든셋

다음 축을 포함한 질의를 선정한다.

- 건성·민감·지성·복합성
- 여드름·피지·색소침착·건조·민감 등 주요 고민
- 계절이 있는 요청과 없는 요청
- 연령·성별이 있는 요청과 없는 요청
- 복합 고민과 단일 고민
- 상품·루틴 지시가 함께 들어왔지만 Case 질의에서 제거되어야 하는 요청

각 평가 질의에는 사람이 원문을 확인한 `relevant_case_ids`가 필요하다. 자동 메타데이터 일치만으로
정답을 만들면 표현은 비슷하지만 답변이 무관한 Case까지 정답이 되므로 사용하지 않는다.

골든 Case ID와 최종 합격 임계치는 아직 확정하지 않는다. 먼저 baseline을 측정하고 골든셋을
검토한 뒤 다음을 사용자와 합의한다.

1. 질의별 relevant Case를 최소 한 건만 둘지, 복수 Case를 모두 표시할지
2. Recall@20 목표값
3. MRR@3 또는 nDCG@3 중 배포 판단의 주 지표

이 세 항목이 확정되기 전에는 품질 개선을 완료로 판정하지 않는다.

### 6.4 평가 출력

평가 CLI는 질의마다 다음을 출력한다.

```text
- canonical case query
- retrieval query 종류와 실제 문자열
- 질의별 Top-20 case_id / vector_similarity
- RRF 융합 Top-20 case_id / RRF score / 출현 질의
- rerank query
- 최종 Top-3 case_id / rerank_score
- relevant Case의 순위
- Hit@20 / Recall@20 / MRR@3 / nDCG@3
- baseline 대비 순위 변화
```

평가 결과는 코드 변경과 분리해 날짜·시간이 포함된 Agent 문서로 기록한다. 측정 당시 사용한
embedding model, reranker model, text version, 대상 DB dump 식별자를 함께 남겨 재현 가능하게
한다.

## 7. 테스트 계획

### 7.1 질의 계획 단위 테스트

- 예시 입력에서 PROFILE, CONCERN, NATURAL_QUESTION 질의가 생성된다.
- `30살`, `여성`, `겨울`, `건조`, `민감`이 필요한 질의에 보존된다.
- `건조`는 허용된 `보습` 문맥으로, `민감`은 허용된 `진정`·`자극 주의` 문맥으로만 확장된다.
- 원문에 없는 `홍조`, `가려움`, `아토피`가 추가되지 않는다.
- 상품, 추천 제품, 루틴 기간·일정 지시는 Case 질의에서 제거된다.
- 의미가 같은 변형 질의는 중복 제거된다.
- 명시 성분 Evidence 직행 경로에서는 Case 검색 질의를 만들지 않는다.

### 7.2 RRF 단위 테스트

- 여러 검색에 반복 등장한 Case가 단일 검색에서만 높은 Case보다 우선되는지 검증한다.
- 동일 Case의 metadata, provenance, page content가 보존되는지 검증한다.
- RRF 동점에서 최대 vector similarity, case_id 순으로 결정되는지 검증한다.
- 성공·NO_RESULTS·ERROR가 섞인 결과의 부분 성공 정책을 검증한다.
- 모든 검색 실패와 모든 검색 무결과를 구분한다.

### 7.3 Workflow 회귀 테스트

- 여러 질의가 한 번의 batch embedding 요청으로 전달된다.
- 각 벡터가 기존 Case 검색 계약으로 전달된다.
- 융합 결과는 최대 20건이다.
- reranker는 `case_rerank_query`를 받는다.
- 관련 성분 선별기는 canonical `case_query`를 받는다.
- reranker 실패 시 RRF Top-3으로 fallback한다.
- 기존 단일 질의 fixture는 fallback으로 계속 동작한다.

### 7.4 검증 명령

```sh
uv run pytest tests/agent/test_query_planning.py -q
uv run pytest tests/agent/test_case_result_fusion.py -q
uv run pytest tests/agent/test_case_two_layer_rag_workflow.py -q
uv run pytest tests/agent/test_interactive_two_layer_rag_cli.py -q
uv run pytest tests/agent -q
uv run ruff check agent tests/agent
```

실제 DB 평가는 unit test와 분리해 명시적으로 실행한다.

```sh
uv run python -m tests.agent.case_retrieval_recall_eval
```

## 8. 구현 순서와 완료 조건

### 8.1 구현 순서

1. Case 검색·rerank 질의 Pydantic 모델과 Enum을 추가한다.
2. 결정적 질의 변형 생성과 금지 확장 테스트를 먼저 작성한다.
3. RRF 융합 클래스와 단위 테스트를 작성한다.
4. `RagWorkflowNodes.search_cases`를 batch 임베딩·복수 검색·융합으로 연결한다.
5. `rerank_cases`와 `extract_case_claims`가 서로 다른 목적의 질의를 쓰도록 연결한다.
6. Trace CLI에 질의별 결과와 융합 결과를 표시한다.
7. Agent 전체 회귀 테스트를 통과시킨다.
8. 골든셋 검토 후 실제 DB baseline/A/B/C 평가를 실행한다.
9. 결과 문서를 공유하고 Recall@20 목표 충족 여부를 판단한다.

### 8.2 코드 완료 조건

- 복수 질의 생성, RRF, 전용 rerank 질의의 단위·통합 테스트가 통과한다.
- 기존 Agent 테스트가 모두 통과한다.
- Backend, DB, data 파일 및 공용 설정을 변경하지 않는다.
- Trace에서 각 검색 질의와 최종 융합 순위를 재현할 수 있다.
- 실패한 질의와 fallback 사용 여부가 숨겨지지 않는다.

### 8.3 품질 완료 조건

- 검토된 골든셋으로 baseline과 변경안을 같은 DB·모델 조건에서 비교한다.
- 관련 Case가 Top-20 밖에 남는 실패 사례를 목록화한다.
- 합의한 Recall@20 및 최종 Top-3 지표를 충족한다.
- 충족하지 못하면 이번 구현에 임의의 추가 키워드를 계속 붙이지 않고,
  `nia_case_text/v2` 또는 메타데이터 후보 합집합을 별도 파트 경계 작업으로 제안한다.

## 9. 후속 판단 기준

다음 중 하나가 확인되면 `embedding_text v2`를 별도 계획으로 검토한다.

- 복수 질의+RRF 이후에도 relevant Case가 반복적으로 Top-20 밖에 있다.
- 전체 질문·답변·추론에 포함된 성분명이 피부 고민보다 검색 순위를 과도하게 지배한다.
- Case 질문부는 관련 있지만 긴 추론부 때문에 cosine similarity가 낮아지는 패턴이 확인된다.
- 계절·피부 상태가 원문에 존재해도 전체 문서 임베딩에서 안정적으로 반영되지 않는다.

이 후속 작업은 `data`의 Case document 생성과 `backend`의 적재·검색 버전 사용에 영향을 줄 수
있으므로, 진행 전에 `data-to-agent` 계약과 파트 범위를 먼저 합의한다.
