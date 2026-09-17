# Backend → Agent 호출 계약

> 상태: **2-Layer 읽기 전용 어댑터 계약 확정 — 읽기 전용 smoke 검증 완료**
>
> 기준: `integration/llm-rag-main`의 agent 공개 계약
>
> 2026-09-11 사용자 확인에 따라 구형 질의 경로 제거와 적재 서비스 전환을 진행한다.

## 1. 목적과 통합 원칙

Backend는 인증, DB 조회·저장, 트랜잭션과 HTTP 변환을 소유하고 Agent는 Intent 분석,
RAG 검색 조정, 재정렬, 답변 생성과 대화 그래프를 소유한다.

이번 통합에서 "현재 코드 버전으로 맞춘다"는 의미는 다음과 같다.

- 기존 동기식 `OpenAiEmbedder` 구현은 유지하지 않는다. 현재 비동기 `TextEmbedder` 계약을
  구현한 `OpenAiTextEmbedder` (`text-embedding-3-small`, 1536차원)를 기본 운영 임베더로
  조립하고, `LocalBgeM3Embedder`는 설정으로 선택할 수 있게 유지한다.
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


class LlmProvider(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    LOCAL = "local"


class OpenAiChatConfig(RagModel):
    api_key: SecretStr
    model: OpenAiChatModel = OpenAiChatModel.GPT_4O_MINI
    timeout_seconds: float = Field(default=30, gt=0)
    max_retries: int = Field(default=1, ge=0)


class LocalChatConfig(RagModel):
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen 3.5:9B"
    api_key: SecretStr = SecretStr("ollama")
    timeout_seconds: float = Field(default=60, gt=0)
    max_retries: int = Field(default=1, ge=0)


class ChatModelConfig(RagModel):
    """채팅 의도 파싱 및 답변 생성에서 사용할 LLM 설정."""

    provider: LlmProvider = LlmProvider.OPENAI
    openai: OpenAiChatConfig | None = None
    local: LocalChatConfig = Field(default_factory=LocalChatConfig)

    @model_validator(mode="after")
    def validate_provider(self) -> Self:
        if self.provider is LlmProvider.OPENAI and self.openai is None:
            raise ValueError("OpenAI LLM을 선택하면 OpenAI 채팅 설정이 필요합니다.")
        return self


class EmbeddingProvider(StrEnum):
    OPENAI = "openai"
    LOCAL = "local"


class OpenAiEmbeddingModel(StrEnum):
    TEXT_EMBEDDING_3_SMALL = "text-embedding-3-small"


class OpenAiEmbeddingConfig(RagModel):
    api_key: SecretStr
    model: OpenAiEmbeddingModel = OpenAiEmbeddingModel.TEXT_EMBEDDING_3_SMALL
    dimensions: int = Field(default=1536, ge=1)
    batch_size: int = Field(default=100, ge=1)
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


class TextEmbeddingConfig(RagModel):
    provider: EmbeddingProvider
    openai: OpenAiEmbeddingConfig | None = None
    local: LocalEmbeddingConfig = Field(default_factory=LocalEmbeddingConfig)

    @model_validator(mode="after")
    def validate_selected_provider(self) -> Self:
        if self.provider is EmbeddingProvider.OPENAI and self.openai is None:
            raise ValueError("OpenAI 임베딩을 선택하면 OpenAI 임베딩 설정이 필요합니다.")
        return self

    def output_dimensions(self) -> int:
        if self.provider is EmbeddingProvider.OPENAI:
            if self.openai is None:
                raise ValueError("OpenAI 임베딩 설정이 없습니다.")
            return self.openai.dimensions
        return BGE_M3_EMBEDDING_DIMENSIONS


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
    chat: ChatModelConfig
    embedding: TextEmbeddingConfig
    reranker: LocalRerankerConfig = Field(default_factory=LocalRerankerConfig)
    retrieval_policy: RagRetrievalPolicy
```

OpenAI API 키는 OpenAI를 선택했을 때만 필요하며, Ollama/로컬 LLM을 선택하면 OpenAI 키 없이도 동작한다.
`ChatModelConfig`·`OpenAiChatConfig`·임베딩 선택·로컬 모델·검색 정책은 `agent/rag/schemas.py`,
`ProductionAgentConfig`는 `agent/factory.py`가 소유한다. 샘플 설정에는 실제 API 키를 넣지 않는다.
Backend는 `TextEmbeddingConfig.output_dimensions()`와 현재 `rag_chunk.embedding` 차원을
조립 단계에서 비교한다. 일치하지 않으면 DB 검색·적재 전에 `RuntimeError`로 중단한다.
검색 임계값이 `null`이면 OpenAI provider에서만 기존 검증값 `0.45`를 적용하고, 로컬 provider는
모델별 검증값을 명시하도록 오류로 중단한다.

### 로컬 임베딩(BGE-M3, 1024차원) 전환 절차 (3단계 후속 작업)

현재 Agent 계층은 `LocalBgeM3Embedder`와 `TextEmbedderFactory`를 통해 로컬 임베딩을 완벽히 지원하며,
DB의 `rag_chunk` 테이블은 기존 1536차원 벡터 데이터(65,196건)를 유지하고 있다.
따라서 **향후 로컬 임베딩으로의 전환은 Agent 코드의 추가 수정 없이, Backend/Data 쪽에서 설정을 주입하고
DB 마이그레이션·재임베딩을 주도하여 수정하면 된다.** 최종 전환 절차는 다음과 같다.

1. **ERD 문서 갱신 및 합의 (규칙 14)**:
   `docs/erd/app.md`에서 `rag_chunk.embedding`의 타입을 `vector(1536)`에서 `vector(1024)`로 수정 합의한다.
2. **DB 모델 및 마이그레이션 생성 (Data 파트)**:
   `models/rag_chunk.py`의 `EMBEDDING_DIMENSION = 1024`로 수정하고, `vector(1024)` 컬럼 변환 및
   HNSW 코사인 인덱스(`ix_rag_chunk_embedding_hnsw`) 재생성 Alembic 마이그레이션을 생성한다.
3. **기존 65,196건 청크의 인플레이스(in-place) 재임베딩**:
   DB 원본 테이블이 없는 `nia_qa`(45,002건)의 유실을 방지하기 위해 테이블을 TRUNCATE하지 않고,
   기존 `rag_chunk.content` 텍스트를 배치 단위로 읽어 BGE-M3(`BAAI/bge-m3`)로 1024차원 벡터를 계산한 뒤
   `embedding` 컬럼을 UPDATE하는 전용 스크립트로 안전하게 재임베딩한다.
   *(CPU 환경 시 약 1~2시간 소요 예상, GPU 확보 시 10~15분 내외)*
4. **설정 및 임계값 전환**:
   `config.yaml`의 `agent.embedding.provider: local`로 변경하고, BGE-M3 기준의
   `agent.retrieval.free_text_min_vector_similarity` 검증값을 반영한다.

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
- 외부 임베딩 API·로컬 모델 로드, 임베딩 차원 불일치, 검색 모델 불일치는 예외 또는
  `LookupStatus.ERROR`로
  드러내며 빈 성공 결과로 숨기지 않는다.
- Backend는 Agent가 반환한 오류를 HTTP 응답으로 변환하되 Agent 타입의 의미를 바꾸지 않는다.

## 7. 아직 합의가 필요한 항목

- `config.yaml`에 OpenAI 키가 없을 때 서버 전체 기동을 막을지 Agent 기능만 비활성화할지
- 향후 로컬 BGE-M3로 전환할 경우의 1024차원 ERD·마이그레이션·재색인 계획과 검증 임계값
- Agent 조립 객체의 lifespan 위치와 로컬 모델 캐시 볼륨
- NIA Q&A의 유지 여부와, 유지한다면 data→agent DTO
- `ChatTurnOutput`을 외부 HTTP 응답으로 노출할 backend→front 계약

## 8. 완료 조건

- Backend import와 FastAPI 기동이 성공한다.
- 기존 main 테스트와 Agent 테스트가 함께 통과한다.
- 운영 질의와 적재가 모두 선택된 `OpenAiTextEmbedder`를 사용한다.
- Intent·답변 생성은 `gpt-4o-mini`, 임베딩은 `text-embedding-3-small`, 재정렬은 로컬
  `BAAI/bge-reranker-v2-m3`를 사용한다.
- OpenAI 임베딩 결과가 1536차원이며 기존 DB 벡터와 `embedding_model` 값이 일치한다.
- 실제 DB를 사용한 vector/BM25 검색과 리랭킹 통합 테스트가 통과한다.

## 9. 최신 dump 기반 2-Layer 읽기 전용 어댑터 (2026-09-17, 19:42 KST 갱신)

> 기준 dump: `data/skincare_latest_2026-09-17.dump`
>
> 복원 DB: `skincare_latest`
>
> 상태: **입출력·Claim 검색·Claim-only 정책 확인 완료**

이 절은 앞 절의 구형 `rag_chunk` 1,536차원 경로를 변경하지 않고, 별도
`claim_chunk`/`evidence_chunk` 경로를 추가하는 계약이다. 최신 dump는 두 레이어 모두
`BAAI/bge-m3`, 1,024차원으로 저장되어 있으므로 OpenAI 1,536차원 임베딩과 섞지 않는다.

### 9.1 범위와 소유권

- Agent는 기존 `ClaimRetriever`, `HybridSearchBackend`, `IngredientRepository`,
  `ProductRepository` 포트와 Pydantic DTO를 소유한다.
- Backend repository는 SQL과 DB 행 전용 Pydantic 모델을 소유한다.
- Backend service adapter는 repository 결과를 Agent DTO로 변환한다.
- Agent는 `AsyncSession`, SQLAlchemy, Backend 구현을 import하지 않는다.
- 이번 경로는 복원된 dump를 읽기만 하며 `models/`, `migrations/`, dump 데이터는 변경하지 않는다.
- 구형 `SqlAlchemyHybridSearchBackend`를 덮어쓰지 않고 2-Layer 전용 구현을 별도 클래스로 둔다.

예정된 호출 시그니처는 기존 Agent 계약을 그대로 사용한다.

```python
class ClaimRetriever(ABC):
    @property
    @abstractmethod
    def embedding_model(self) -> LocalEmbeddingModel: ...

    @abstractmethod
    async def search(self, request: ClaimSearchRequest) -> ClaimSearchResult: ...


class HybridSearchBackend(ABC):
    @abstractmethod
    async def search(self, request: HybridSearchRequest) -> HybridSearchResult: ...


class IngredientRepository(ABC):
    @abstractmethod
    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult: ...


class ProductRepository(ABC):
    @abstractmethod
    async def search(self, request: ProductSearchRequest) -> ProductSearchResult: ...

    @abstractmethod
    async def get(self, request: ProductGetRequest) -> ProductGetResult: ...
```

Evidence 검수 상태는 저장값만 신뢰한다. 통합 fixture라는 이유로 `NULL` 상태를 검증 완료로
승격하는 별도 완화 정책은 두지 않는다.

### 9.2 Claim 조회와 DTO 매핑

`ClaimSearchRequest`는 `annotation_version`을 필수로 받고, `query`와 `skin_concerns`를 순서대로
결합한 문자열을 BGE-M3로 임베딩한다. 이미 계산한 `query_embedding`이 전달되면 같은 벡터를
재사용한다. DB 조회는 같은 `embedding_model`과 정확히 일치하는 `annotation_version`만 cosine
검색하며 여러 annotation run을 자동으로 섞거나 최신값으로 추정하지 않는다.

지원 Claim 타입은 계약에서 Evidence topic 매핑이 확정된 아래 세 종류로 제한한다.

- `ingredient_effect_claim` → `EvidenceClaimTopic.EFFICACY`
- `usage_instruction` → `EvidenceClaimTopic.USAGE_INSTRUCTION`
- `combination_claim` → `EvidenceClaimTopic.COMBINATION`

| DB 값 | Agent 값 | 규칙 |
| --- | --- | --- |
| `claim_chunk.id` | `ClaimHit.claim_chunk_id` | UUID 문자열 |
| `claim_document.source_record_id` | `ClaimHit.source_record_id` | 원문 그대로 |
| `claim_document.annotation_version` | `ClaimHit.annotation_version` | 요청 버전과 반드시 일치 |
| `claim_chunk.statement_id` | `ClaimHit.statement_id` | 원문 그대로 |
| `claim_chunk.statement_type` | `ClaimHit.statement_type` | 동일 Enum 값만 허용 |
| `claim_chunk.content` | `ClaimHit.content` | 원문 그대로 |
| `claim_chunk.decision` | `ClaimHit.decision` | 동일 Enum 값만 허용 |
| `claim_chunk_ingredient.*` | `ClaimHit.ingredient_refs` | 성분 연결별 DTO로 보존 |
| `claim_chunk.support_status` | `ClaimHit.support_status` | 동일 Enum 값만 허용 |
| cosine similarity | `ClaimHit.score` | 원점수 보존 |

DB 컬럼 설명에 따라 Claim 통과 조건은 다음 결정적 규칙으로 고정한다.

- `claim_chunk.decision`은 운영 검색 인덱스 필터이며 `ingestible_*`만 기본 검색 대상이다.
- `claim_document.production_ready`는 사람 최종 검수 완료 여부이지만 런타임 필수 필터로
  강제하지 않는다.
- `decision`은 Agent DTO에도 보존하며 Agent가 허용값을 다시 검증한다.
- `production_ready`는 저장소 provenance이며 최소 `ClaimHit`에는 복제하지 않는다. 이 값으로
  검색 결과를 제외하거나 Claim 지원 상태를 바꾸지 않는다.
- `decision`이 `ingestible_*`가 아닌 행과 `matching_status`가 `rejected`인 성분 연결은 검색
  후보에서 제외한다.
- `matching_status=matched`인 성분만 `EvidenceQueryAnchor.ingredient_refs`로 승격한다.
  unresolved 성분은 Agent가 raw name으로 다시 해소하지 않고 보류한다.

현재 dump의 Claim 5건은 모두 `decision=ingestible_structured`이므로 Claim 검색 후보에
포함된다. `production_ready=false` 때문에 Claim 결과가 0건이 되지 않는다.

### 9.3 Evidence 조회와 Citation 매핑

`HybridSearchRequest.embedding_model`은 반드시 `BAAI/bge-m3`여야 하고 벡터 길이는 1,024여야
한다. `target_ids`는 `evidence_chunk_ingredient.ingredient_id`에 OR 필터로 적용한다. 개별 성분
한 개와 연결된 Evidence를 `PAIR` 근거로 승격하지 않는다. 따라서 복합 질문은 개별 근거만
반환하며, 조합 근거 없음 판정은 기존 Agent 규칙에 맡긴다.

| DB 값 | Agent 값 | 규칙 |
| --- | --- | --- |
| `pubmed_abstract` | `EvidenceSourceType.PAPER` | 명시적 Enum 매핑 |
| `evidence_chunk.id` | `EvidenceRecord.evidence_id` | UUID 문자열 |
| `evidence_document.source_id` | `EvidenceRecord.source_id` | `PMID:<id>` 보존 |
| `evidence_document.source_title` | `EvidenceRecord.source_title` | 원문 그대로 |
| `evidence_chunk.content` | `EvidenceRecord.text`, `RagChunkDraft.content` | 두 DTO에서 동일 원문 사용 |
| `evidence_chunk.chunk_id` | `RagChunkDraft.chunk_id` | 원문 그대로 |
| `section`/`chunk_index` | `field_id`/`locator` | 빈 section은 오류, locator는 결정적으로 조립 |
| Evidence 성분 연결 | `EvidenceRecord.target_ids` | UUID 문자열, 중복 제거 |
| `document_date`/`retrieved_at` | `published_at`/`collected_at` | ISO-8601 문자열 |
| `jurisdiction` | `jurisdiction`, `conditions.jurisdiction` | 저장값만 사용 |
| `url`, `doi`, `pmid` | `url`, `source_reference` | URL은 그대로, reference는 DOI와 PMID를 결정적으로 조립 |
| `claim_topics` | `RagChunkDraft.intents` | LLM이 아니라 명시적 topic→`QuestionIntent` 룰로 변환 |
| `peer_reviewed_study` | `RagConfidenceTier.STRUCTURED_KNOWLEDGE` | 근거 종류 tier로 사용하며 검수 상태는 별도 판정 |

Citation의 제목, URL, PMID, DOI는 DB 메타데이터만 사용한다. LLM 출력으로 출처 식별자를 만들거나
보완하지 않는다.

`document_status=NULL`은 `EvidenceReviewStatus.UNREVIEWED`로 변환한다. 검색 결과에는 남기되
Citation과 `SUPPORTED` 판정에는 사용하지 않는다. 해당 Claim은 `INSUFFICIENT`가 되고,
성분은 `CLAIM_ONLY` 상품 후보로 유지한다. 현재 저장 계약에는 `verified` 값이 없으므로
`VERIFIED` 승격 조건은 보류 상태다. Data 파트와 검수 상태 계약을 확정하기 전에는
`final`/`amended_final` 또는 `peer_reviewed_study`를 임의로 검수 완료로 해석하지 않는다.

### 9.4 Ingredient와 Product 조회

- Ingredient resolve는 표준 한글/영문명, 정규화명, 구명칭의 정확 일치만 먼저 지원한다.
- 일치 1건은 `SUCCESS`, 복수는 `ambiguous_candidates`, 없음은 `NO_RESULTS`다.
- Claim은 `matched` UUID만 사용한다. unresolved raw name은 Ingredient resolve로 다시 추론하지
  않으며 Data 파트가 후속 annotation run에서 확정해야 한다.
- Product 검색은 `product_ingredient.match_acceptance=confirmed`와 non-null `ingredient_id`만 사용한다.
- 요청한 성분 ID 중 하나 이상을 포함한 상품을 반환하되, 같은 상품이 여러 성분에서 검색돼도
  `product.id` 기준으로 한 번만 반환한다.
- `ProductRecord.ingredient_ids`에는 해당 상품의 confirmed 성분 ID만 중복 없이 넣는다.
- 상품의 이름·분류·source·관찰 시각은 저장값만 매핑하고, 제형·사용감·사용법을 추론하지 않는다.

### 9.5 상태와 실패 계약

- 검색 성공 + 결과 있음: `SUCCESS`
- 검색 성공 + 결과 없음: `NO_RESULTS`
- BGE-M3 이외 모델, 1,024 이외 차원, 현재 미지원 statement type/필터: `UNSUPPORTED`
- DB 오류, JSON/Pydantic 변환 오류, 저장 Enum 불일치: 원인을 포함한 `ERROR`
- 예외를 빈 성공 결과로 바꾸지 않는다.
- 읽기 전용 smoke 실행기는 실제 LLM 응답 품질 평가와 분리한다. 먼저 검색 DTO, Claim→Evidence,
  Claim-only Product, Citation metadata의 결정적 연결을 검증한다.

### 9.6 후속 평가 항목

BGE-M3 자유 질의 임계값은 현재 데이터 5건만으로 확정하지 않는다. 첫 통합 구현에서는
성분 ID 필터 검색을 우선하고, 자유 질의 임계값 튜닝은 평가 데이터가 늘어난 뒤 별도 진행한다.
