# Backend → Agent 호출 계약

> 상태: **통합 방향 합의 — DB 차원·운영 저장소는 후속 확인 필요**
>
> 기준: `integration/llm-rag-main`의 agent 공개 계약
>
> 2026-09-11 사용자 확인에 따라 구형 질의 경로 제거와 적재 서비스 전환을 진행한다.

## 1. 목적과 통합 원칙

Backend는 인증, DB 조회·저장, 트랜잭션과 HTTP 변환을 소유하고 Agent는 Intent 분석,
RAG 검색 조정, 재정렬, 답변 생성과 대화 그래프를 소유한다.

이번 통합에서 "현재 코드 버전으로 맞춘다"는 의미는 다음과 같다.

- 기존 `OpenAiEmbedder`를 새 인터페이스에 맞춰 유지하지 않는다. 임베딩은 Agent가 조립하는
  `LocalBgeM3Embedder` (`BAAI/bge-m3`)로 교체한다.
- 기존 `RagDocument`, `RetrievedChunk`, `RagQueryResult`와 UUID·tuple 기반 구조를 호환용
  복사본으로 남기지 않는다. Backend 어댑터가 ORM 조회 결과를 현재 Agent 소유 Pydantic DTO로
  변환한다.
- Backend의 SQL과 트랜잭션 책임은 유지한다. Agent가 DB 세션이나 SQLAlchemy 모델을 직접
  import하지 않는다.
- 기존 `RagQueryService`의 독립 질의 파이프라인은 `ChatService.handle_turn`과 병행하지 않는다.
  사용자 질의의 운영 진입점은 `ChatService.handle_turn` 하나로 통합한다.
- 기존 `RagIngestionService`의 원본 교체·재색인 트랜잭션 책임은 유지하되, 청킹·임베딩은
  현재 `RagIngestionPipeline`의 비동기 계약을 호출한다.

## 2. 운영 조립

### 부르는 대상

```python
ProductionAgentFactory.create(
    dependencies: ProductionAgentDependencies,
    config: ProductionAgentConfig,
    execution_limits: ExecutionLimits | None = None,
    context_limits: ContextLimits | None = None,
) -> ProductionAgentApplication
```

Backend가 애플리케이션 lifespan 또는 동등한 프로세스 단위 조립 지점에서 한 번 호출한다.
개발용 `DevelopmentAgentFactory`, fixture 저장소와 `InMemorySaver`는 운영에 주입하지 않는다.

### 설정

설정 소스는 `config.yaml` 하나다. Backend가 설정을 읽어 아래 Agent 소유 모델로 변환한다.
`.env`는 Docker Compose 변수에만 사용하며 Agent는 dotenv나 `os.environ`을 직접 읽지 않는다.

```python
class OpenAiChatModel(StrEnum):
    GPT_4O_MINI = "gpt-4o-mini"


class OpenAiChatConfig(RagModel):
    api_key: SecretStr
    model: OpenAiChatModel = OpenAiChatModel.GPT_4O_MINI
    timeout_seconds: float = Field(default=30, gt=0)
    max_retries: int = Field(default=1, ge=0)


class LocalEmbeddingModel(StrEnum):
    BGE_M3 = "BAAI/bge-m3"


class LocalEmbeddingConfig(RagModel):
    model: LocalEmbeddingModel = LocalEmbeddingModel.BGE_M3
    device: LocalModelDevice | None = None
    batch_size: int = Field(default=DEFAULT_EMBEDDING_BATCH_SIZE, ge=1)
    cache_folder: str | None = Field(default=None, min_length=1)
    local_files_only: bool = False


class LocalRerankerModel(StrEnum):
    BGE_RERANKER_V2_M3 = "BAAI/bge-reranker-v2-m3"


class LocalRerankerConfig(RagModel):
    model: LocalRerankerModel = LocalRerankerModel.BGE_RERANKER_V2_M3
    device: LocalModelDevice | None = None
    batch_size: int = Field(default=DEFAULT_RERANKER_BATCH_SIZE, ge=1)
    max_length: int = Field(default=DEFAULT_RERANKER_MAX_LENGTH, ge=1)
    cache_folder: str | None = Field(default=None, min_length=1)
    local_files_only: bool = False


class RagRetrievalPolicy(RagModel):
    free_text_min_vector_similarity: float = Field(ge=-1, le=1)
    rrf_k: int = Field(default=60, gt=0)
    rerank_candidate_limit: int = Field(default=DEFAULT_RERANK_CANDIDATE_LIMIT, ge=1)


class ProductionAgentConfig(AgentModel):
    openai: OpenAiChatConfig
    embedding: LocalEmbeddingConfig = Field(default_factory=LocalEmbeddingConfig)
    reranker: LocalRerankerConfig = Field(default_factory=LocalRerankerConfig)
    retrieval_policy: RagRetrievalPolicy
```

`OpenAiChatConfig`·로컬 모델·검색 정책은 `agent/rag/schemas.py`,
`ProductionAgentConfig`는 `agent/factory.py`가 소유한다. 샘플 설정에는 실제 API 키를 넣지 않는다.

## 3. 사용자 요청 호출

### 부르는 대상

```python
async def ChatService.handle_turn(request: ChatServiceRequest) -> ChatTurnOutput
```

### 입력과 출력

아래 타입은 `agent/schemas.py`가 소유한다. Backend API 스키마를 이 타입의 복사본으로 만들지
않고, API 요청을 이 타입으로 명시적으로 변환한다.

```python
class ChatTurnInput(AgentModel):
    chat_room_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    candidate_set_id: str | None = None
    routine_version: int | None = Field(default=None, ge=1)


class AuthenticatedChatContext(AgentModel):
    actor_id: str = Field(min_length=1)
    chat_room_id: str = Field(min_length=1)


class ChatServiceRequest(AgentModel):
    auth: AuthenticatedChatContext
    turn: ChatTurnInput


class ChatTurnOutput(AgentModel):
    chat_room_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    assistant_message_id: str = Field(min_length=1)
    status: ChatStatus
    message: str = Field(min_length=1)
    intents: list[Intent] = Field(default_factory=list)
    follow_up_question: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
    error_code: ErrorCode | None = None
    retryable: bool = False
    save_handoff: RoutineSaveHandoff | None = None
```

예시 입력:

```json
{
  "auth": {"actor_id": "user-1", "chat_room_id": "room-1"},
  "turn": {
    "chat_room_id": "room-1",
    "request_id": "request-1",
    "message": "레티놀과 비타민 C를 같이 써도 돼?"
  }
}
```

## 4. Backend가 구현해 주입할 포트

Agent가 소유한 포트의 구현 클래스는 `backend/services/`에서 조립하고, SQL은
`backend/repositories/`에만 둔다.

| Agent 포트 | Backend 책임 |
| --- | --- |
| `ChatHistoryRepository` | 방 권한, 메시지·요약·아티팩트 조회, 턴 멱등성, 저장 staging/commit |
| `ProductRepository` | 상품 조건 검색과 버전 고정 조회 |
| `IngredientRepository` | 성분명·별칭 해소와 모호성 반환 |
| `RoutinePlanner` | 운영 루틴 계획·검증 구현 또는 별도 승인된 구현 주입 |
| `HybridSearchBackend` | pgvector/BM25 조회와 Agent 검색 DTO 변환 |

### 하이브리드 검색 입력과 출력

다음 타입은 `agent/rag/schemas.py`가 소유한다.

```python
class LookupStatus(StrEnum):
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class EvidenceSearchRequest(RagModel):
    known_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)
    query: str = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)
    combination_target_ids: list[str] = Field(default_factory=list)


class HybridSearchRequest(RagModel):
    request: EvidenceSearchRequest
    vector: EmbeddingVector
    embedding_model: str


class HybridSearchResult(RagModel):
    status: LookupStatus
    vector_results: list[RetrievedChunk] = Field(default_factory=list)
    bm25_results: list[RetrievedChunk] = Field(default_factory=list)
    error_message: str | None = None
```

```python
async def HybridSearchBackend.search(request: HybridSearchRequest) -> HybridSearchResult
```

Backend 구현은 `target_ids`의 OR 검색과 `combination_target_ids`의 관계 근거 검색을 구분한다.
지원할 수 없는 필터를 무시하지 않고 `UNSUPPORTED`로 반환하며, 검색 장애는 `ERROR`, 정상
무결과는 `NO_RESULTS`로 반환한다. 성공 결과는 vector/BM25 원점수 내림차순을 보존한다.

ORM 행은 `RetrievedChunk.chunk.evidence`의 출처, 원문 조건, 검수 상태를 임의로 추론하지 않고
저장된 값만 사용해 변환한다. `embedding_model`이 요청 모델과 다르면 검색 성공으로 반환하지 않는다.

## 5. RAG 적재 호출

Backend의 `RagIngestionService`가 원본 조회, DB 쓰기와 commit/rollback 경계를 소유한다.
Agent는 다음 저장소 독립 호출만 제공한다.

```python
async def RagIngestionPipeline.run(
    documents: list[RagDocument],
) -> list[EmbeddedChunk]
```

`RagDocument`, `EmbeddedChunk`는 `agent/rag/schemas.py`가 소유한다. Backend는 ORM을 직접
넘기지 않고 `agent/rag/loaders/data_records.py`의 입력 DTO와 `DataRecordMapper`를 사용해
`EvidenceRecord`로 변환한다. 결과의 `EmbeddingVector.values`만 Backend repository 입력 DTO로
변환한다. 재적재 도중 임베딩에 실패하면 기존 데이터 교체를 commit하지 않는다.

청크의 안정적인 DB 필드 매핑을 위해 현재 `RagChunkDraft`는 `field_id`를 함께 반환한다.

```python
class RagChunkDraft(RagModel):
    chunk_id: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    evidence: EvidenceRecord
    intents: list[QuestionIntent] = Field(default_factory=list)
    confidence_tier: RagConfidenceTier = RagConfidenceTier.UNKNOWN
```

NIA Q&A는 현재 Agent에 대응하는 변환 계약이 없다. 기존 로더를 임의로 되살리지 않고 data→agent
계약이 합의될 때까지 적재 대상에서 제외한다.

## 6. 실패 계약

- 방 없음과 권한 없음은 각각 `ROOM_NOT_FOUND`, `ROOM_FORBIDDEN`으로 반환한다.
- 동일 `request_id`의 본문 충돌과 처리 중 재요청은 각각 `REQUEST_CONFLICT`,
  `REQUEST_IN_PROGRESS`로 반환한다.
- 그래프·도구·저장 실패는 `ChatTurnOutput.error_code`와 `retryable`에 반영한다.
- 로컬 모델 로드, 임베딩 차원 불일치, 검색 모델 불일치는 예외 또는 `LookupStatus.ERROR`로
  드러내며 빈 성공 결과로 숨기지 않는다.
- Backend는 Agent가 반환한 오류를 HTTP 응답으로 변환하되 Agent 타입의 의미를 바꾸지 않는다.

## 7. 아직 합의가 필요한 항목

- `config.yaml`에 OpenAI 키가 없을 때 서버 전체 기동을 막을지 Agent 기능만 비활성화할지
- 1536차원 `rag_chunk.embedding`을 BGE-M3 1024차원으로 바꾸는 ERD·마이그레이션·재색인 계획
- BGE-M3 검증셋으로 다시 정할 `free_text_min_vector_similarity`
- Agent 조립 객체의 lifespan 위치와 로컬 모델 캐시 볼륨
- NIA Q&A의 유지 여부와, 유지한다면 data→agent DTO
- `ChatTurnOutput`을 외부 HTTP 응답으로 노출할 backend→front 계약

## 8. 완료 조건

- Backend import와 FastAPI 기동이 성공한다.
- 기존 main 테스트와 Agent 테스트가 함께 통과한다.
- 운영 질의와 적재 모두 `OpenAiEmbedder`를 참조하지 않는다.
- Intent·답변 생성만 `gpt-4o-mini`를 호출하고 임베딩·재정렬은 로컬 모델을 사용한다.
- DB 벡터 차원과 BGE-M3 결과 차원이 일치하며 기존 데이터 재색인이 완료된다.
- 실제 DB를 사용한 vector/BM25 검색과 리랭킹 통합 테스트가 통과한다.
