# Agent 계층

`agent/`는 FastAPI나 DB 세션을 만들지 않는 LLM·RAG 실행 계층이다. 백엔드는
`ChatService.handle_turn()`만 호출하고, 실제 저장소·모델·체크포인터는 생성 시 주입한다.

설계 기준은 다음 문서다.

- [`RAG_YK/LLM_RAG_DEVELOPMENT_REQUEST.md`](../RAG_YK/LLM_RAG_DEVELOPMENT_REQUEST.md)
- [`RAG_YK/LLM_RAG_PIPELINE.md`](../RAG_YK/LLM_RAG_PIPELINE.md)
- [`RAG_YK/LLM_RAG_DB_CONTRACT.md`](../RAG_YK/LLM_RAG_DB_CONTRACT.md)

## 현재 구성

| 파일 | 책임 |
| --- | --- |
| `agent/schemas.py` | 채팅 입출력, 세션 스냅샷, LangGraph 상태 Enum/Pydantic 모델 |
| `agent/ports.py` | LLM, 제품·성분·루틴·히스토리 포트 |
| `agent/adapters.py` | `FakeLlmClient`, fixture 조회기, 인메모리 히스토리 |
| `agent/context.py` | 요약 범위와 최근 대화가 겹치지 않는 컨텍스트 구성 |
| `agent/prompts.py` | 실제 LLM 어댑터가 사용할 목적별 프롬프트 템플릿 |
| `agent/nodes.py` | 해석, 식별, 정보 판단, 작업 실행, 검증, 응답 노드 |
| `agent/graph.py` | `StateGraph` 분기와 체크포인터 실행 경계 |
| `agent/service.py` | 방 권한 확인, 중복 방지, 실행, 결과 저장 조정 |
| `agent/factory.py` | 개발용 구현과 `InMemorySaver` 조립 |
| `agent/rag/pipeline.py` | 근거 검색과 적용 조건 평가 조립 |
| `agent/rag/ports.py` | RAG 파이프라인이 검색 구현에 요구하는 포트 |
| `agent/demo.py` | 두 채팅방을 사용하는 오프라인 데모 |

그래프는 다음 순서로 동작한다.

```text
prepare_turn → understand_request → resolve_entities → assess_information
  ├─ ask_user → finalize_response → END
  └─ route_task ↔ process_task → validate_result
       ├─ revise_result → validate_result
       └─ finalize_response → END
```

`needs_input`도 완료된 턴으로 저장한다. 다음 사용자 답변은 같은 방의 새 `request_id`로
실행하며, 대기 질문과 원래 Intent는 완료 스냅샷에서 복원한다.

## 실행과 검사

전체 개발 환경 준비는 [`SETUP.md`](../SETUP.md)를 따른다.

```bash
uv run python -m agent.demo
uv run pytest -q
uv run ruff check agent tests
uv run pyrefly check agent tests
```

데모는 실제 논문이나 제품으로 오해되지 않도록 모든 상품·근거·계획에 `is_demo=true`를
설정한다. 유료 API 키, DB, 벡터 서비스가 없어도 실행된다.

## 구현 상태

| 구분 | 현재 상태 |
| --- | --- |
| 실제 구현 | LangGraph 분기, Pydantic 상태, 채팅방 격리, 후보 참조, 추가 질문, 실행 제한, 컨텍스트 요약, 중복 요청, 저장 재시도 |
| 개발 대체 구현 | 규칙 기반 `FakeLlmClient`, 키워드 근거 검색, 제품·성분 fixture, 최소 루틴 계획기, 인메모리 히스토리와 체크포인터 |
| 미구현 | 실제 LLM, 임베딩·하이브리드 검색, 실제 제품·문헌 DB, 운영 체크포인터, 고도화된 루틴 최적화, FastAPI 엔드포인트 |

검색 점수는 안전성이나 근거 품질로 사용하지 않는다. fixture 계획의 주 2회 배치는 실행
프레임 검증을 위한 서비스 정책일 뿐 임상 사용법이 아니다.

## 실제 시스템 연결 위치

실제 연동은 `agent/ports.py`의 계약을 구현한 뒤 `DevelopmentAgentFactory` 대신 운영 조립
코드에서 주입한다.

- LLM 공급자: `LlmClient`
- 제품·성분 DB: `ProductRepository`, `IngredientRepository`
- 문헌·벡터 검색: `EvidenceRetriever`
- 일정 계산·검증: `RoutinePlanner`
- 채팅 원문·결과 스냅샷: `ChatHistoryRepository`
- LangGraph 영속 상태: `BaseCheckpointSaver`

DB 쿼리는 실제 어댑터를 만들 때도 `backend/repositories/`에만 둔다. `agent`에서는 DB
세션을 만들지 않고 포트를 통해 결과 모델만 받는다.

## DB 담당자 검토가 필요한 계약 변경

개발 구현은 원 요청서의 `begin_turn`과 `complete_turn` 사이에 `stage_turn_result`를
추가했다. 그래프 실행은 끝났지만 최종 응답 저장이 실패한 경우, 같은 `request_id` 재시도에서
LLM과 도구를 다시 호출하지 않고 이미 생성한 응답·스냅샷의 저장만 재시도하기 위해서다.

운영 DB에서는 다음 중 하나로 합의해야 한다.

1. 생성 결과를 별도 재시도 가능 상태로 먼저 기록한 뒤 `complete_turn`에서 확정한다.
2. 백엔드가 같은 보장을 제공하는 outbox 또는 동등한 원자적 저장 경계를 구현한다.

현재 인메모리 구현은 단일 프로세스에서만 이 계약을 검증한다. 다중 프로세스 잠금, 장애 후
보존, 체크포인터와 외부 DB 사이의 분산 트랜잭션을 해결했다고 간주하지 않는다.

## RAG 파이프라인 상세

### 책임과 경계

현재 RAG 파이프라인의 실행 진입점은 `agent/rag/pipeline.py`의 `EvidencePipeline`이다.
파이프라인은 근거를 직접 저장하거나 특정 벡터 DB 클라이언트를 생성하지 않는다.
`EvidenceRetriever` 구현을 생성자에서 주입받아 검색하고, 각 검색 결과의 적용 조건을
`EvidenceApplicabilityEvaluator`로 평가한 뒤 하나의 `EvidenceBundle`로 반환한다.

```text
사용자 질문
→ Intent·조건·참조 해석
→ 성분·제품 식별
→ EvidenceSearchRequest 생성
→ EvidenceRetriever.search
→ EvidenceSearchResult
→ EvidenceApplicabilityEvaluator.assess
→ EvidenceBundle(검색 결과 + 근거별 적용성)
→ 답변 artifact·citation·unresolved 생성
→ 전체 결과 검증
```

이 구조를 사용하는 이유는 검색 기술과 근거 적용 판단을 분리하기 위해서다. 관련 문장을
찾았다는 사실만으로 해당 근거가 현재 제품이나 사용 조건에 그대로 적용된다고 판단하지 않는다.

### 입출력 계약

RAG 입출력은 `agent/rag/schemas.py`의 Enum과 Pydantic 모델로만 전달한다.

| 모델 | 주요 내용 |
| --- | --- |
| `EvidenceSearchRequest` | 검색문, 정규화된 성분·제품 대상 ID, 최대 검색 개수 |
| `EvidenceSearchResult` | 조회 상태, 근거 레코드 목록, 실패 메시지 |
| `EvidenceRecord` | 근거 ID, 출처 ID, 문서 버전, 원문 구간, 위치, 적용 조건, 검수 상태 |
| `EvidenceConditions` | 농도, 제형, 경로, 사용 방식, 기간 |
| `ApplicabilityAssessment` | 근거 ID, 적용 가능·제한·불가·미상 상태와 이유 |
| `EvidenceBundle` | 검색 결과와 각 근거의 적용성 평가 목록 |

`EvidenceRecord.text`는 답변 모델이 만든 요약이 아니라 검색으로 찾은 원문 구간을 전달하기
위한 필드다. `locator`와 `document_version`을 함께 보존해 나중에 실제 문서 저장소를 연결했을
때 어느 버전의 어느 위치를 사용했는지 추적할 수 있게 한다.

### 검색 결과 상태

`LookupStatus`는 다음 네 상태를 구분한다.

| 상태 | 의미 | 응답 처리 |
| --- | --- | --- |
| `success` | 조회가 정상적으로 끝났고 결과가 있음 | 근거와 적용 범위를 답변에 연결 |
| `no_results` | 조회는 성공했지만 관련 결과가 없음 | `no_evidence`로 기록하고 부분 결과 반환 |
| `unsupported` | 요청 조건을 현재 조회기가 지원하지 않음 | 조건을 완화하지 않고 미지원 항목 표시 |
| `error` | 저장소 접근이나 검색 도구가 실패함 | `tool_failure`로 기록하고 재시도 가능 여부 표시 |

따라서 검색 도구 실패를 “관련 논문 없음”으로 바꾸지 않으며, 검색 결과가 없다는 사실을
“안전함”이나 “효과 없음”으로 해석하지 않는다.

### 적용성 평가

적용성 평가 대상은 농도, 제형, 사용 경로, 사용 방식, 기간이다. 근거에 조건이 적혀 있지만
현재 제품·사용자 맥락에서 대응 값을 알 수 없으면 `limited`로 반환하고 `적용 조건 미상`을
남긴다. 미공개 농도나 pH는 사용자에게 반복해서 묻거나 추정하지 않고 `unresolved`에 둔다.

현재 최소 평가기는 다음 범위만 구현한다.

- 근거에 명시된 조건과 현재 알려진 조건의 누락 여부 확인
- 누락 조건이 있으면 `limited`, 없으면 fixture 범위의 `applicable` 반환
- 근거의 검수 상태와 `is_demo` 표시 유지

조건 간 실제 충돌 판정, 성분의 정확한 화학적 형태 비교, 완제품과 개별 성분 근거의 구분,
상충 논문 통합은 아직 구현하지 않았다. 이 항목들은 실제 데이터 스키마와 검수 정책이 정해진
뒤 평가 규칙으로 추가해야 한다.

### 현재 실행 분기와의 연결 상태

| 분기 | 현재 RAG 연결 | 남은 작업 |
| --- | --- | --- |
| `evidence_qa` | 성분 식별 → 근거 검색 → 적용성 평가 → 답변·인용 생성까지 연결됨 | 실제 문헌 저장소와 실제 LLM 답변 생성 연결 |
| `product_discovery` | 제품·성분 fixture의 구조화 검색만 사용 | 효능·병용 주장이 필요한 추천에서 공통 근거 파이프라인 호출 |
| `routine_planning` | 제품 fixture의 사용 설명과 최소 계획 검증만 사용 | 제품별 근거·병용 조건 검색과 검수된 일정 규칙 연결 |

단순히 특정 성분이 포함된 제품을 찾는 요청에는 논문 검색을 강제하지 않는다. 반면 추천 이유에
효능·병용·내약성 주장이 들어가거나 루틴 제약을 근거로 확정하려면 공통 RAG 파이프라인을
호출해야 한다. 현재 fixture 단계에서는 이 판단 로직이 상품·루틴 분기에 아직 연결되지 않았다.

### 현재 개발용 검색 구현

`FixtureEvidenceRetriever`는 성분 ID와 한글·영문 키워드로 로컬 fixture를 찾는다.
모든 레코드는 다음 원칙을 지킨다.

- `is_demo=true`, `review_status=demo`로 표시한다.
- 실제 논문처럼 보이는 가짜 DOI나 URL을 만들지 않는다.
- 검색 결과에 안전성 확률이나 근거 품질 점수를 부여하지 않는다.
- 강제로 주입한 검색 실패와 정상적인 무결과를 서로 다른 상태로 반환한다.

이 구현은 포트와 그래프 흐름을 검증하기 위한 것이며 임베딩, 벡터 검색, 하이브리드 검색이
완료됐음을 의미하지 않는다.

### 사전 데이터 파이프라인 상태

목표 사전 처리 흐름은 다음과 같다.

```text
AI Hub 성분 자료·공식 제품 정보·논문
→ 원문·출처·버전 보존
→ 문서 로딩
→ 청킹과 원문 위치 부여
→ 성분·제품 식별 및 조건 추출
→ 임베딩·검색 색인 생성
→ 검수 상태·상충·누락 기록
→ EvidenceRetriever가 조회할 저장소 연결
```

현재 `agent/rag/loaders/`, `chunking/`, `embedding/`, `retrieval/`, `generation/`에는 패키지
골격만 있고 실제 구현은 없다. 실제 작업은 다음 순서로 진행한다.

1. 원문과 출처·문서 버전·위치를 손실 없이 보존하는 로더를 구현한다.
2. 청크마다 원문 위치와 문서 버전을 유지하는 청킹 계약을 구현한다.
3. 키워드 검색 기준선을 먼저 만들고 임베딩·벡터 저장소를 교체 가능한 구현으로 추가한다.
4. 검색 결과를 `EvidenceRecord`로 변환하고 무결과·미지원·실패를 구분한다.
5. 실제 제품·사용 조건을 `EvidenceConditions`에 연결해 적용성 평가를 확장한다.
6. 상품 추천과 루틴 분기 중 근거 주장이 필요한 경로에만 공통 파이프라인을 연결한다.
7. 고정 평가셋으로 검색 관련도와 조건 오적용, 인용 지원 여부를 각각 검증한다.

실제 DB 조회가 필요해지면 SQLAlchemy 쿼리는 `backend/repositories/`에 두고,
`EvidenceRetriever` 구현은 주입받은 조회 계약만 사용한다. `agent/rag/`에서 DB 세션이나
네트워크 클라이언트를 직접 만들지 않는다.
