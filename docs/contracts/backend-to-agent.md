# Backend → Agent 호출 계약

> 최종 업데이트: 2026-09-22 KST
> 최신 변경 의도: Evidence 사용 가능성·출처 lane·사용자 응답 계약 확정
>
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

이 절의 기존 `document_status=NULL → UNREVIEWED → 답변 제외` 규칙은 2026-09-22 합의에 따라
13.1절의 초안으로 대체한다. `document_status`는 문서 생명주기 메타데이터로만 보존하고 답변
가능 여부를 결정하지 않는다.

### 9.4 Ingredient와 Product 조회

- Ingredient resolve는 표준 한글/영문명, 정규화명, 구명칭의 정확 일치만 먼저 지원한다.
- 일치 1건은 `SUCCESS`, 복수는 `ambiguous_candidates`, 없음은 `NO_RESULTS`다.
- Claim은 `matched` UUID만 사용한다. unresolved raw name은 Ingredient resolve로 다시 추론하지
  않으며 Data 파트가 후속 annotation run에서 확정해야 한다.
- Product 검색은 `product_ingredient.match_acceptance=confirmed`와 non-null `ingredient_id`만 사용한다.
- 요청한 성분 ID 중 하나 이상을 포함한 상품을 반환하되, 같은 상품이 여러 성분에서 검색돼도
  `product.id` 기준으로 한 번만 반환한다.
- `ProductSearchFilters.category`가 있으면 `ProductCategory.code`를
  `product.service_category`와 정확히 비교한다. 성분과 카테고리 조건은 SQL에서 함께 적용하고,
  그 뒤에 정렬과 `ProductSearchRequest.limit`을 적용한다. 먼저 제한된 상품을 Agent가 사후
  필터링하는 방식은 실제 후보를 누락하므로 사용하지 않는다.
- 카테고리가 없으면 기존처럼 confirmed 성분 연결만으로 검색한다. Agent의 결과 재검증은
  Backend 필터를 대신하지 않으며 방어적 계약 확인으로만 유지한다.
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

## 10. NIA Case 검색 및 런타임 Claim 추출 계약 — 2026-09-21 02:19 KST

> 상태: **핵심 구현 완료, 2026-09-21 10:20 KST 검증 갱신**

피부 고민형 질의는 유사 NIA Case를 먼저 찾고, rerank Top-3의 원문에서 현재 질문과 직접 관련된
성분 Claim만 런타임 LLM 구조화 출력으로 추출한다. 전체 Case의 offline Claim annotation과
`claim_chunk` 벡터 검색은 P3 필수 경로에서 제외한다.

명시적인 성분 질의는 Case 검색과 Claim 추출을 모두 건너뛰고 기존 Evidence 경로를 유지한다.
Case와 런타임 Claim은 탐색 정보이며 공인 Evidence가 아니다.

### 10.1 Case 검색 타입과 포트

타입은 `agent/rag/case_schemas.py`, 포트는 `agent/rag/ports.py`가 소유한다.

```python
from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import Field, FiniteFloat, model_validator

from agent.rag.schemas import EmbeddingVector, LookupStatus, RagModel


class CaseDatasetSplit(StrEnum):
    TRAINING = "training"
    VALIDATION = "validation"


class CaseProvenance(RagModel):
    archive_name: str = Field(min_length=1)
    member_name: str | None = Field(default=None, min_length=1)
    line_number: int = Field(ge=1)


class CaseMetadata(RagModel):
    target_concern: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)


class CaseSearchRequest(RagModel):
    query: str = Field(min_length=1)
    query_embedding: EmbeddingVector
    text_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    candidate_limit: int = Field(default=20, ge=3)


class CaseSearchHit(RagModel):
    case_id: str = Field(min_length=1)
    page_content: str = Field(min_length=1)
    text_version: str = Field(min_length=1)
    dataset_split: CaseDatasetSplit
    metadata: CaseMetadata
    provenance: CaseProvenance
    vector_similarity: FiniteFloat
    rerank_score: FiniteFloat | None = None


class CaseSearchResult(RagModel):
    status: LookupStatus
    hits: list[CaseSearchHit] = Field(default_factory=list)
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "CaseSearchResult": ...


class CaseRerankRequest(RagModel):
    query: str = Field(min_length=1)
    candidates: list[CaseSearchHit] = Field(min_length=1)
    limit: int = Field(default=3, ge=1)


class CaseRerankResult(RagModel):
    model: str = Field(min_length=1)
    hits: list[CaseSearchHit] = Field(min_length=1, max_length=3)


class CaseRetriever(ABC):
    @abstractmethod
    async def search(self, request: CaseSearchRequest) -> CaseSearchResult: ...


class CaseReranker(ABC):
    @abstractmethod
    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult: ...
```

`CaseSearchResult`의 검증 규칙은 기존 검색 DTO와 같다. `SUCCESS`에는 hit이 있어야 하고, 성공이
아닌 상태에는 hit을 넣지 않으며, `ERROR`에는 원인 메시지가 필요하다.

NIA 원문의 `evidence_sources`는 Backend 저장소에는 보존하지만 Agent 검색 DTO에는 넣지 않는다.
이를 공식 Citation으로 오인해 답변에 노출하는 경로를 차단하기 위해서다.

### 10.2 Backend Case 검색 책임

Backend는 `BackendNiaCaseRetriever`를 구현해 주입한다.

- 운영 검색은 `training`과 `validation`을 합친 3,581건 전체를 사용한다.
- `dataset_split`은 후보 제외 조건이 아니라 provenance와 평가 분석용으로 반환한다.
- `text_version`, `embedding_model`이 정확히 일치하는 행만 검색한다.
- 질의 벡터가 BGE-M3 1,024차원인지 조회 전에 검증한다.
- cosine similarity 내림차순으로 1차 후보를 반환한다.
- BGE reranker는 1차 후보만 읽고 최종 Top-3를 반환한다.
- ORM과 DB session은 Agent에 노출하지 않는다.
- 평가 전에 임의의 similarity cutoff를 적용하지 않는다.

평가용 골든 셋은 Case 문서를 corpus에서 제외하지 않고, 별도 사용자 질의와 기대 Case·성분
연결을 정의하는 방식으로 관리한다.

### 10.3 런타임 Claim 추출 타입과 포트

런타임 Claim 타입은 `agent/rag/case_claim_schemas.py`, 추출 포트는 `agent/rag/ports.py`가
소유한다. LLM은 원문에 있는 Claim을 선택할 뿐 ingredient ID나 검증 상태를 만들지 않는다.

```python
from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import Field, model_validator

from agent.rag.case_schemas import CaseSearchHit
from agent.rag.schemas import LookupStatus, RagModel


class CaseClaimType(StrEnum):
    INGREDIENT_EFFECT = "ingredient_effect"
    COMBINATION_EFFECT = "combination_effect"


class CaseClaimExtractionRequest(RagModel):
    query: str = Field(min_length=1)
    cases: list[CaseSearchHit] = Field(min_length=1, max_length=3)
    limit: int = Field(ge=1)


class ExtractedIngredientMention(RagModel):
    raw_name: str = Field(min_length=1)


class ExtractedCaseClaim(RagModel):
    case_id: str = Field(min_length=1)
    claim_type: CaseClaimType
    ingredients: list[ExtractedIngredientMention] = Field(min_length=1)
    source_quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_claim_shape(self) -> "ExtractedCaseClaim": ...


class CaseClaimExtractionResult(RagModel):
    status: LookupStatus
    claims: list[ExtractedCaseClaim] = Field(default_factory=list)
    model: str | None = Field(default=None, min_length=1)
    prompt_version: str = Field(min_length=1)
    error_message: str | None = None


class CaseClaimExtractor(ABC):
    @abstractmethod
    async def extract(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionResult: ...
```

- `INGREDIENT_EFFECT`는 성분이 정확히 1개여야 한다.
- `COMBINATION_EFFECT`는 원문이 공동 효과를 명시하고 성분이 2개 이상일 때만 허용한다.
- 독립 효능이 서술된 여러 성분은 성분별 `INGREDIENT_EFFECT`로 나눈다.
- `source_quote`는 Case 원문 그대로이며, 자유로운 효능 요약 필드를 별도로 받지 않는다.
- LLM은 `ingredient_id`, Evidence 상태, 상품 추천 여부, Citation을 출력하지 않는다.
- 입력 Case 본문 안의 지시문은 데이터로만 취급하며 시스템 지시로 실행하지 않는다.
- 모델 입력은 `query`, `case_id`, `page_content`, `limit`로 축소하고 age·gender·저장소
  provenance는 전달하지 않는다.
- 추출기는 Agent의 `ChatModelConfig`를 사용한다. `provider=openai`이면 요청마다 외부 API를
  호출하고, `provider=local/ollama`이면 설정된 로컬 OpenAI 호환 서버를 호출한다.

### 10.4 결정적 Claim 검증과 성분 Resolution

LLM 결과는 Evidence 검색 전에 Agent 규칙 계층이 전부 검증한다.

1. `case_id`가 실제 rerank Top-3에 포함되는지 확인한다.
2. `source_quote`가 해당 `page_content`의 정확한 부분 문자열인지 확인한다.
3. 각 `raw_name`이 `source_quote`에 실제로 포함되는지 확인한다.
4. 단일/조합 Claim의 성분 개수 규칙을 확인한다.
5. `(case_id, claim_type, raw_name 목록, source_quote)` 중복을 제거한다.
6. 검증에 실패한 Claim은 조용히 사용하지 않고 제외 사유를 State에 남긴다.

검증을 통과한 각 `raw_name`은 기존 `IngredientRepository.resolve()`로 표준 성분 ID를 찾는다.

- 정확히 매칭된 성분만 Evidence/Product anchor로 승격한다.
- `NO_RESULTS`는 raw name과 Case provenance를 unresolved로 남긴다.
- 여러 후보가 반환되면 임의 선택하지 않고 ambiguous 상태로 남긴다.
- 런타임 LLM에 표준 ID 선택을 다시 맡기지 않는다.

`EvidenceQueryOrigin`에는 `CASE_CLAIM`을 추가한다. Evidence anchor는 요청 ID, Case ID, Claim
타입, exact quote, 확정 성분 ID로 결정적으로 만든다.

- 단일 Claim: 성분 ID 1개, `IngredientScope.SINGLE`
- 조합 Claim: 모든 성분이 매칭된 경우에만 `IngredientScope.MULTI`와 `ALL`
- 조합 Claim 일부만 매칭되면 단일 성분 Claim으로 축소하지 않는다.
- Evidence query text는 원문 성분명과 exact quote를 사용한다.

### 10.5 LangGraph 상태와 라우팅

- Case, 런타임 Claim, Evidence는 각각 `CaseBundle`, `CaseClaimBundle`, `EvidenceBundle`로 분리한다.
- 피부 고민형:
  `embed_case_query → search_cases → rerank_cases → extract_case_claims → validate_case_claims → resolve_claim_ingredients → verify_claims → product`
- 명시 성분형: 기존 `ingredient resolution → evidence → product` 경로를 유지한다.
- 기존 호출 호환을 위해 `RagRoute.CLAIM_THEN_EVIDENCE` 이름은 유지하고, 운영 기본 연결을
  `search_cases`로 바꾼다.
- 기존 DB `ClaimRetriever`는 P3 피부 고민형 기본 경로에 주입하지 않는다.
- Case 본문이나 LLM 출력은 공식 Citation으로 렌더링하지 않는다.
- Evidence `NO_RESULTS`/`UNREVIEWED`여도 매칭된 성분의 Claim-only 상품 후보는 유지한다.

### 10.6 실패와 fallback 계약

| 단계 | 상태 | 처리 |
| --- | --- | --- |
| Case 검색 | `NO_RESULTS` | 성분을 추측하지 않고 탐색 결과 없음으로 종료 |
| Case 검색 | `ERROR` | 오류를 State에 남기고 partial/error 응답 |
| Case reranker | 실패 | vector 순위 Top-3로 fallback하고 이력을 남김 |
| Claim 추출 | `NO_RESULTS` | Case 본문에서 성분을 임의 보충하지 않음 |
| Claim 추출 | `ERROR` | 오류를 State에 남기고 Evidence/Product 단계를 건너뜀 |
| Claim 규칙 검증 | 일부 실패 | 실패 Claim만 제외하고 사유를 남김 |
| 성분 Resolution | unresolved/ambiguous | Claim 문구는 보존하고 Evidence/Product anchor에서 제외 |
| Evidence | 허용 출처 근거 없음 | 기존 정책대로 Claim-only 상품 후보 유지 |

현재 production Claim index가 없으므로 전역 Claim RAG를 자동 fallback으로 사용하지 않는다.
향후 offline Claim index를 운영에 채택하면 별도 정책과 골든 셋 검증 후 fallback을 다시 계약한다.

### 10.7 Backend 책임 변화

P3에서 Backend가 새로 담당하는 것은 NIA Case 벡터 조회와 DTO 변환이다. 기존 성분·Evidence·상품
Repository와 어댑터는 그대로 사용한다.

- `nia_case_document` 검색 SQL: Backend Repository
- Case 결과 DTO 변환: Backend Service adapter
- 런타임 Claim 추출·검증·상태 관리: Agent
- raw 성분명 표준 ID 조회: 기존 Backend `IngredientRepository` 구현
- Evidence/Product 조회: 기존 Backend 구현
- offline `claim_document`/`claim_chunk` 조회: P3 필수 경로 아님

기존 Claim 모델·Repository·적재 코드는 삭제하지 않는다. 후속 offline 최적화와 비교 평가에
사용할 수 있으며 이번 방향 변경에는 모델·마이그레이션이 필요하지 않다.

offline `ClaimRetriever`는 명시적으로 주입한 비교·개발 모드에서만 기존 `search_claims` 경로를
사용한다. 운영 기본 Case 경로는 Claim `annotation_version` 없이도 조립할 수 있다.

### 10.8 데이터 및 평가 기준

- Case 3,581건과 BGE-M3 Case 임베딩은 준비돼 있다.
- 실제 Case `page_content`는 평균 약 1,859자이고, 중앙값 기준 Top-3 합계는 약 5,547자다.
- production Claim annotation은 0/3,581건이며 P3 선행 조건이 아니다.
- Case 검색 적합도, Claim exact-quote 통과율, 성분 매칭률, Evidence/Product 도달률을 분리해 측정한다.
- 골든 셋에는 사용자 질의, 기대 Top-3 Case, 기대 성분 raw name/ID, 제외해야 할 성분을 기록한다.
- 런타임 추출 결과의 모델명과 `prompt_version`을 보존해 재현성과 회귀를 비교한다.

### 10.9 구현 검증 결과 — 2026-09-21 10:20 KST

- Agent DTO·포트, Backend Case Retriever, 런타임 extractor·validator 구현 완료
- Case → 성분 Resolution → Evidence anchor → Claim-only Product LangGraph 연결 완료
- Evidence 0건 Claim-only 상품 유지와 명시 성분 Case 우회 테스트 통과
- 실제 PostgreSQL NIA Case 벡터 후보 20건 조회 테스트 통과
- 전체 기본 테스트 `449 passed, 3 deselected`
- Case와 Evidence reranker는 한 CrossEncoder 모델 인스턴스를 공유
- 외부 OpenAI 포함 실제 E2E는 Top-3 NIA 원문 전송 승인 후 실행
- reranker fallback, Claim 추출 오류, unresolved 성분 차단 회귀 테스트 통과
- 골든 셋, ambiguous 분기, 다중 Case provenance 세부 회귀는 후속 평가 범위

## 11. DB 기반 Product Taxonomy 조회 계약 — 2026-09-21 15:45 KST

### 11.1 부르는 대상

통합 CLI가 Agent를 조립하기 전에 Backend의 다음 비동기 메서드를 호출한다.

```python
class TwoLayerProductTaxonomyProvider:
    async def load(self) -> ProductTaxonomy: ...
```

- 입력 파라미터는 없다.
- 반환 타입 `ProductTaxonomy`의 소유 위치는 `agent/rag/schemas.py`다.
- DB 세션과 조회 SQL은 Backend가 소유하며 Agent는 DB를 직접 import하지 않는다.

### 11.2 출력과 저장값 매핑

```python
class ProductClassification(RagModel):
    code: str
    name: str
    aliases: list[str]


class ProductCategory(ProductClassification):
    pass


class ProductTaxonomy(RagModel):
    version: str
    categories: list[ProductCategory]
    textures: list[ProductTexture]
    skin_feels: list[ProductSkinFeel]
```

`product` 테이블의 NULL이 아닌 `(service_category, product_type_normalized)` 조합과 상품 수를
집계하고 다음과 같이 변환한다.

- `service_category` → `ProductCategory.code`, `ProductCategory.name`
- 같은 `service_category`의 `product_type_normalized` 집합 → 해당 카테고리의 `aliases`
- `textures`, `skin_feels` → 빈 목록
- `version` → 정렬된 DB 분류값으로 계산한 결정적 digest 버전

`product_type_normalized`는 세부 제품 유형이지 제형 또는 사용감이 아니므로 `textures`나
`skin_feels`로 승격하지 않는다. 상품 DTO의 category 코드도 `service_category`를 사용해 Taxonomy
코드와 실제 필터 대상이 일치하게 한다. 두 분류가 NULL인 상품은 현재 지원 Taxonomy에 넣지 않는다.

### 11.3 실패 계약

- 조회 SQL·DB 연결·DTO 변환 실패: 원인을 포함한 `RuntimeError`
- 유효한 `service_category`가 0건: 빈 개발용 fixture로 대체하지 않고 `RuntimeError`
- 일부 미분류 상품: 전체 로딩 실패로 처리하지 않고 Taxonomy 집계에서 제외

통합 CLI는 이 실패를 숨기지 않고 시작 단계에서 종료한다. 운영 분류를 읽지 못한 상태에서
fixture 분류로 실행하면 Agent가 지원한다고 판단한 필터와 실제 상품 코드가 달라질 수 있기 때문이다.

## 12. Case 관련 성분 선별 및 사용법 전달 계약 — 2026-09-21 16:12 KST

이 절은 10.3~10.5의 런타임 Case Claim 생성 방식 중 LLM 책임을 축소한다. Backend가 반환하는
`CaseSearchHit` 계약은 바꾸지 않으며 변경 범위는 Agent 내부의 Top-3 분석과 루틴 입력 조립이다.

### 12.1 LLM 관련 성분 선별

LLM은 효능 Claim, 조합 관계 또는 표준 ID를 만들지 않는다. 사용자 질문과 관련 있고 Top-3 Case
원문에 실제로 적힌 성분만 다음 후보 형태로 반환한다.

```python
class SelectedCaseIngredient(RagModel):
    case_id: str
    raw_name: str


class CaseIngredientSelectionModelOutput(RagModel):
    ingredients: list[SelectedCaseIngredient]
```

- 피부 고민과 무관한 성분은 반환하지 않는다.
- `claim_type`, `combination_relation_quote`, `ingredient_id`, Evidence 상태는 LLM 출력에 없다.
- Agent 규칙 계층이 Top-3 `case_id`, 원문 안의 `raw_name` 존재 여부와 중복을 검증한다.
- 내부 호환 DTO의 `source_quote`는 검증 대상인 `raw_name` 자체로 결정적으로 만든다. LLM이 긴
  인용문을 복사하지 않으므로 말줄임표나 개행 변형 때문에 유효 성분 전체가 탈락하지 않는다.
- 검증된 후보는 기존 단일 성분 Evidence/Product 경로와 연결하기 위한 내부 호환 DTO로 변환한다.
- Evidence 검색문은 LLM이 만든 효능 문장이 아니라 `표준 성분명 + 사용자 질문`으로 결정적으로 만든다.

### 12.2 NIA Case 사용법 구간

`NiaCaseDocument.page_content`에 보존된 번호·제목 구조에서 `사용법 및 관리방안` 구간은 규칙으로
추출한다. 별도 LLM으로 구간 경계를 추측하지 않는다.

```python
class CaseUsageGuidance(RagModel):
    source_id: str
    case_id: str
    text: str
    ingredient_ids: list[str]
```

- Top-3 Case에서 선별·표준화된 성분명이 사용법 구간에도 명시된 경우만 만든다.
- 최종 선택 상품의 `ingredient_ids`와 교차되는 안내만 루틴 입력에 사용한다.
- Case 사용법은 공식 제품 사용법이나 검수 Evidence가 아니므로 항상 warning으로 처리한다.
- 제품 공식 directions와 검수 Evidence의 required 규칙을 덮어쓰지 않는다.
- 적용 상품이 없거나 성분 연결이 불명확한 일반 조언은 스케줄 규칙으로 만들지 않는다.

루틴 연결 순서는 다음과 같다.

```text
Case Step 3 규칙 추출
→ 선택 성분·최종 상품 연결
→ RoutineRuleSource(CASE_USAGE_GUIDANCE)
→ LLM Rule 후보 추출
→ exact quote·상품 범위 결정적 검증
→ WARNING Rule
→ RoutineDraftGenerator
→ 최종 일정 결정적 검증
```

## 13. Evidence 사용 가능성·출처 lane·사용자 응답 계약 — 2026-09-22

> 상태: **2026-09-22 사용자 확인 완료 / 구현 기준 계약**
>
> Agent와 Backend 양쪽 구현은 이 절을 기준으로 변경한다.

### 13.1 `document_status`의 의미

`evidence_document.document_status`는 원문 문서의 생명주기 메타데이터다. Evidence를 답변에
사용할 수 있는지 판정하는 검수 상태로 사용하지 않는다.

- Backend는 저장값을 삭제하거나 `verified`로 바꿔 쓰지 않는다.
- Agent는 `document_status`에서 파생된 `EvidenceReviewStatus`를 답변 생성 차단 조건이나
  사용자 경고 조건으로 사용하지 않는다.
- 답변 가능성은 허용 출처, 질문 축 관련성, 적용 조건, non-demo 여부, 인용문 검증으로 판정한다.
- `document_status`가 `NULL`, `final`, `amended_final` 등 어떤 값이어도 검색 순위와 Citation
  포함 여부에는 영향을 주지 않는다.
- 데이터베이스 스키마와 마이그레이션은 변경하지 않는다.

### 13.2 질문 축별 Evidence 출처 lane

출처 선택 타입은 Agent가 소유하고 Backend는 요청받은 lane을 SQL에서 적용한다.

```python
class EvidenceSourceLane(StrEnum):
    EFFICACY = "efficacy"
    SAFETY = "safety"
    REGULATION = "regulation"


class EvidenceSourcePlan(RagModel):
    lane: EvidenceSourceLane
    primary_source_types: list[EvidenceSourceType] = Field(min_length=1)
    fallback_source_types: list[EvidenceSourceType] = Field(default_factory=list)


class EvidenceSearchRequest(RagModel):
    known_conditions: EvidenceConditions = Field(default_factory=EvidenceConditions)
    query: str = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1)
    combination_target_ids: list[str] = Field(default_factory=list)
    source_plan: EvidenceSourcePlan | None = None
```

Agent의 결정적 질문 축 분류 결과를 다음 검색 계획으로 변환한다.

| 질문 축 | primary | fallback |
| --- | --- | --- |
| 효능·피부 고민·추천 근거 | PubMed(`PAPER`), CIR | 없음 |
| 주의사항·안전성 | CIR, PubMed(`PAPER`) | 없음 |
| 사용제한·규제 | MFDS | CIR, PubMed(`PAPER`) |

- 효능과 주의가 함께 있으면 두 출처 집합이 같으므로 CIR·PubMed를 모두 허용한다.
- 규제·한도·금지·허용·사용제한 신호가 있으면 `REGULATION` lane을 우선한다.
- Backend Repository는 lane별 `source_type` 조건을 정렬과 `LIMIT` 전에 적용한다.
- primary 검색 결과를 먼저 사용하고, 요청 상한이 남을 때만 fallback 결과로 채운다.
- fallback 자료는 MFDS 규제 사실처럼 표현하지 않고 실제 출처 유형을 Citation에 보존한다.
- NIA Case는 성분 후보 탐색 자료이며 Evidence 출처 lane에 포함하지 않는다.

### 13.3 미지원 상품 조건과 고민 기반 RAG

- `unsupported_product_conditions`가 있어도 Case → Evidence 성분 탐색을 중단하지 않는다.
- 나이, 성별, 계절, 피부 고민은 상품 SQL 필터가 아니라 사용자 문맥으로 보존한다.
- DB에서 검증할 수 없는 명시적 상품 조건은 `unresolved`로 알리고 해당 조건을 만족한다고
  단정한 상품 후보는 만들지 않는다.
- 미지원 조건 하나 때문에 근거 기반 성분·주의사항 답변 전체를 단일 오류 문구로 대체하지 않는다.
- `모공`, `피지`, `여드름`, `건조`, `홍조`, `칙칙함`처럼 지원하는 고민 표현은 LLM 출력이
  누락돼도 결정적 정책에서 `skin_concerns`로 보완한다.

### 13.4 사용자 응답과 내부 식별자

- `statement_id`, `case-claim:<UUID>`, `evidence_id`, ingredient UUID는 사용자 본문에 출력하지 않는다.
- 근거 부족 결과는 표준 성분명 기준으로 중복 제거해 한 문단으로 요약한다.
- 내부 식별자는 구조화 artifact, trace, 로그에서만 유지한다.
- `citation_validation_failed`는 내부 사유로 보존하되 사용자에게는 어떤 출처·조건이 부족했는지
  설명 가능한 문장으로 변환한다.
- 일부 성분만 검증되면 검증된 답변을 먼저 제공하고 나머지 성분의 한계를 별도로 알린다.

### 13.5 실패 계약

- 허용된 primary·fallback 출처 모두 무결과: `NO_RESULTS`
- DB 또는 DTO 변환 실패: 원인을 포함한 `ERROR`
- 지원하지 않는 source type: 조용히 무시하지 않고 `UNSUPPORTED`
- 인용문 검증 실패: 해당 생성 문장만 제외하고, 검증된 문장이 하나도 없을 때만
  `CITATION_VALIDATION_FAILED`
