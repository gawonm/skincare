# agent 구조와 연결 계약 검토

검토일: 2026-09-10. 변경 전 agent 기준 `5457e95`, main 기준 `c2769bc`.
동적 분류와 후보 표시 보완은 현재 작업 트리의 후속 변경이며 아직 커밋·병합하지 않았다.

상태: agent 담당 범위에서 작성한 기존 코드 검토서. 구현된 시그니처와 미합의 항목을
구분한다. 상대 담당자 승인이나 실제 main 병합·운영 연결 완료를 의미하지 않는다.

## 1. 이번에 받은 방향

- agent 구현은 `feature/llm-rag-pipeline` 기준으로 유지한다.
- main의 `ProductIngredientService`, `ProductIngredientRepository`,
  `IngredientMasterRepository`를 보존한다.
- main에만 있는 agent RAG 5개 파일은 제외하는 방향이다. 정확한 목록은
  [agent README](../README.md#main-통합-시-보존제외-기준)에 있다.
- backend·data의 코드를 agent 안에 복제하지 않는다. DB 모델과 공용 설정을 변경하지 않는다.

## 2. 채팅 호출 계약: 이미 구현됨

소유: `agent/service.py`, `agent/schemas.py`.

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

호출: `await ChatService.handle_turn(request)`. 입력 예시는
`auth={actor_id: user-a, chat_room_id: room-a}`,
`turn={chat_room_id: room-a, request_id: request-1, message: 보습 제품 추천해줘}`다.
`auth`는 서버가 확인한 사용자 정보이며 요청 본문 값을 그대로 신뢰하지 않는다.
출력 상태는 `completed`, `needs_input`, `partial`, `error`이며 `needs_input`도 이번 요청은
완료로 저장하고 다음 사용자 답변을 새 요청으로 처리한다.

### 저장 계약과 실패

`agent/ports.py`의 `ChatHistoryRepository`가 현재 기준이다.

| 메서드 | 입력 → 출력 | 요구 의미 |
| --- | --- | --- |
| `get_authorized_room` | `RoomLookupRequest → AuthorizedRoom` | 소유자 확인 및 방별 thread 연결 |
| `begin_turn` | `BeginTurnRequest → BeginTurnResult` | 신규·진행 중·완료·충돌·생성 결과 임시 저장 상태 구분 |
| `get_messages` | `MessagePageRequest → MessagePage` | 방별 순번과 페이지 조회 |
| `get_artifacts` | `ArtifactLookupRequest → ArtifactLookupResult` | 해당 방의 후보·루틴만 반환 |
| `get_session_context` | `SessionContextRequest → SessionContextResult` | 마지막 완료 스냅샷 복원 |
| `stage_turn_result` | `StageTurnResultRequest → None` | 생성 결과와 스냅샷을 재시도용으로 보관 |
| `complete_turn` | `CompleteTurnRequest → None` | 저장된 결과·대화·스냅샷·완료 상태를 일관되게 확정 |
| `mark_turn_failed` | `MarkTurnFailedRequest → None` | 실패 기록·실행권 해제 |
| `save_summary` | `SaveSummaryRequest → SaveSummaryResult` | 오래된 요약의 덮어쓰기 방지 |

모두 비동기다. 입출력 모델은 `agent/schemas.py` 소유이며 backend 폴더에 복제하지 않는다.
`complete_turn`의 현재 반환은 기존 제안서의 표와 달리 `None`이다. 재전송 시 저장된 응답은
`begin_turn`의 결과로 복원한다. 단계별 DB 트랜잭션과 프로세스 간 동시성 보장은 backend가
구현해야 하며 개발용 인메모리 구현의 통과로 대신할 수 없다.

`RoomNotFoundError`, `RoomAccessDeniedError`는 구조화된 채팅 오류로 변환된다.
그래프 실행·문맥 복원 중 처리하는 오류와 `TurnStorageError`의 결과 저장 오류도
`ChatTurnOutput`에 반영한다. 모든 예외가 변환되는 것은 아니다. 예를 들어 `begin_turn`의
저장 장애, 권한 조회의 예상 밖 장애, 실패 기록 자체의 장애는 호출자에게 전파될 수 있다.
backend가 HTTP 오류 매핑·로그·재시도 정책을 정해야 한다.

## 3. RAG 호출·주입 계약: 이미 구현됨

| 대상 | 실제 시그니처 | 담당 |
| --- | --- | --- |
| `RagIngestionPipeline.run` | `async (list[RagDocument]) → list[EmbeddedChunk]` | agent가 청킹·임베딩, backend가 저장 |
| `EvidencePipeline.run` | `async (EvidenceSearchRequest) → EvidenceBundle` | agent가 검색 호출·적용성·생성 조정 |
| `HybridSearchBackend.search` | `async (HybridSearchRequest) → HybridSearchResult` | backend가 DB 검색 어댑터 제공 |
| `EvidenceRetriever.search` | `async (EvidenceSearchRequest) → EvidenceSearchResult` | 하이브리드 검색 또는 별도 구현 주입 |
| `TextEmbedder.embed` | `async (EmbeddingRequest) → EmbeddingResult` | agent의 모델 어댑터 또는 대체 구현 |
| `ClaimGenerator.generate` | `async (ClaimGenerationRequest) → GeneratedClaims` | agent의 생성 어댑터 또는 대체 구현 |

소유: `agent/rag/ports.py`, `agent/rag/schemas.py`, `agent/rag/pipeline.py`.

```python
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

예시: `query="나이아신아마이드 효능"`, `target_ids=["<IngredientMaster UUID 문자열>"]`,
`limit=5`, `known_conditions={}`. 조합 질문에는 조합 자체의 대상 ID들을 별도로 전달한다.
벡터 값은 `EmbeddingVector.values`에서 얻는다. 문자열 ID를 DB 키로 해석하는 책임은
backend 어댑터에 있으며 상품·성분 ID 구분 방식은 합의가 필요하다.

벡터·BM25 결과는 각 원점수 내림차순으로 반환한다. agent가 RRF를 계산한다.
`target_ids`는 OR 조건이며 여러 대상이면 대상별 top-k를 유지하므로 최종 청크 수가
`limit`보다 많을 수 있다. `combination_target_ids`에 대응하는 관계 근거도 검색해야 한다.
미지원 조건은 `UNSUPPORTED`, 무결과는 `NO_RESULTS`, 실패는 `ERROR`로 구분한다.
조건을 무시한 결과를 성공으로 반환하지 않는다.

중복 청크 ID에 서로 다른 원문이 연결되거나 임베딩 수가 맞지 않으면 `ValueError`를 낸다.
독립 적재·질의 호출자는 모델/API 장애도 처리해야 한다. agent 적재 함수는 DB를 쓰지 않으므로
예외 시 DB 변경 취소와 최종 commit은 backend 서비스가 관리한다.

`DataRecordMapper`가 반환하는 `EvidenceRecord`에서 `RagDocument.fields`를 구성하는
정책은 아직 미합의다. 검수 상태는 공식 출처 여부와 다르며 매퍼는 자료를 자동으로
`VERIFIED`로 승격하지 않는다. 현재 답변 생성기는 검수된 비데모 근거와 지원 신뢰도 티어를
요구하므로 실제 색인 연결만으로 검증 답변이 자동 활성화되는 것은 아니다.

## 4. 반드시 보존할 backend 3개 파일과 접점

### ProductIngredientService

현재 역할은 전성분 파싱 결과의 매칭·적재다. `create(session)`은 표준 성분 후보를
얻어 매칭기를 만들고, `ingest(source, parse_result, parser_version)`는 스냅샷·토큰을 저장한다.
agent의 상품 검색이나 추천을 대신하는 서비스가 아니다. 기존 적재 호출과 데이터 의존성을
유지하고 agent의 요청 경로에서 재적재를 수행하지 않는다.

### ProductIngredientRepository

현재 공개 메서드는 `find_snapshot`, `create_snapshot`, `sync_tokens`,
`count_by_match_acceptance`다. 이름이 비슷해도 agent의 `ProductRepository.search/get`과
다른 역할이며 직접 주입할 수 없다. 상품 카탈로그와 선택한 옵션·스냅샷을 읽는 조회 경로는
backend 담당자에게 요청해야 한다.

기존 데이터는 토큰 순서, 옵션 연결 상태, 성분 매칭 상태, 농도 원문을 보존한다.
agent의 현재 `ProductRecord.ingredient_ids` 목록만으로는 이 정보를 모두 전달할 수 없다.
확정 매칭과 검토 후보를 합치거나 여러 옵션의 성분을 한 제품에 합치는 것은 허용하지 않는다.
조회 계약에서 선택할 상품·옵션·스냅샷, 확인된 ID의 범위, 미해결 항목 전달 방식을 합의해야 한다.

### IngredientMasterRepository

`list_all_as_candidates() → list[IngredientCandidate]`는 기존 매칭 파이프라인에 필요하므로
보존한다. `IngredientCandidate`는 data 타입이며 agent가 직접 import하지 않는다.
backend 어댑터가 아래와 같이 agent 소유 `IngredientRecord`로 변환할 수 있다.

| 기존 후보 필드 | agent 필드 | 제약 |
| --- | --- | --- |
| `ingredient_id` | `ingredient_id` | 동일 UUID를 문자열로 표현 |
| `standard_name_ko` | `canonical_name` | 정규 한국어 이름 |
| `standard_name_en`, `old_names_ko/en` | `aliases` | 실제 제공된 이름만 사용 |
| 현재 후보에 없음 | `ingredient_code`, `source_version` | 없으면 `None`; 임의 생성 금지 |
| 실제 DB에서 조회 | `is_demo` | `False`; 근거 검수 상태와는 무관 |

`DataRecordMapper.ingredient`의 `IngredientMasterData`는 `ingredient_code`와
`source_version`까지 요구하므로 기존 후보를 그대로 받을 수 없다. 후보 조회를 바꾸기보다
기존 후보 → `IngredientRecord`의 별도 어댑터를 backend에서 검토한다. 기존 정규화·매칭기의
정책과 agent의 이름 해석을 동등하다고 간주하지 않는다.

## 5. ProductCategory·ProductTexture 검토: 동적 분류로 변경

변경 전 카테고리는 `cleanser/toner/serum/moisturizer/sunscreen`의 고정 분류였다.
main의 상품 DB는 `category1/2/3` 원본 문자열을 보관한다. DB 컬럼이나 저장 엔진이 바뀐다고
agent Enum도 반드시 바뀌는 것은 아니다. 원본 분류를 서비스 분류로 매핑하는 계약이 있으면
agent 인터페이스를 유지할 수 있다. 다만 이 다섯 값이 서비스의 전체 분류라는 합의는 없다.

변경 전 제형은 `light/rich/gel/cream`이었다. 앞의 두 값은 사용감, 뒤의 두 값은 제형이라
한 축의 배타적인 선택지로 보기 어렵다. 가벼운 크림을 둘 중 하나로만 표현하면 정보가 손실된다.
main 상품 모델에는 제형·사용감 컬럼이 없으며 상품명으로 확정값을 만들어서는 안 된다.

변경 전 `ProductRecord`는 category, texture, directions, version을 필수로 요구했다. main 카탈로그에는
directions와 불변 상품 version도 직접 대응하지 않는다. 이 필드들을 운영 연결 가능한 확정
계약이라고 표시할 수 없다. 스냅샷의 parser_version도 상품 버전과 동일하지 않다.

사용자 선택: 코드·이름 DTO와 지원 목록을 주입하는 동적 분류로 전환한다.
`ProductCategory`와 `ProductTexture`는 Enum에서 Pydantic 모델로 변경했으며 `code`, `name`,
선택적 `aliases`를 갖는다. 제형(`ProductTexture`)과 사용감(`ProductSkinFeel`)은 분리한다.
`ProductTaxonomy`에 목록 버전과 각 축의 지원 목록을 담아 `AgentDependencies`로 주입한다.
목록에 없는 LLM 코드나 이전 세션의 폐기된 코드는 조회 전에 미지원으로 처리한다.
코드는 표시 이름과 독립적인 안정적인 식별자여야 하며, 이름만 같다고 코드를 합치지 않는다.

상품 응답의 `category`, `texture`, `skin_feel`, `directions`, `version`은 확인되지 않으면
`None`을 허용한다. 미상인 상품 속성은 해당 조건과 일치한다고 간주하지 않는다.
지원 목록은 필터로 실제 처리할 수 있는 값만 제공하고 빈 목록은 해당 축의 필터 미지원을 뜻한다.
기존의 문자열 Enum 직렬화는 코드·이름 객체로 바뀌므로 backend와 저장된 세션의 호환성 검토가
필요하다. 운영 스냅샷 마이그레이션은 이번 agent 작업에서 임의로 구현하지 않는다.

### 변경된 공개 타입과 조립 계약

소유: `agent/rag/schemas.py`. 아래는 필드 정의이며 실제 클래스의 중복 코드 검증도 적용된다.

```python
class ProductClassification(RagModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)


class ProductCategory(ProductClassification):
    """상품 카테고리."""


class ProductTexture(ProductClassification):
    """데이터에서 확인된 제형."""


class ProductSkinFeel(ProductClassification):
    """데이터에서 확인된 사용감."""


class ProductTaxonomy(RagModel):
    version: str = Field(min_length=1)
    categories: list[ProductCategory] = Field(default_factory=list)
    textures: list[ProductTexture] = Field(default_factory=list)
    skin_feels: list[ProductSkinFeel] = Field(default_factory=list)


class ProductSearchFilters(RagModel):
    category: ProductCategory | None = None
    texture: ProductTexture | None = None
    skin_feel: ProductSkinFeel | None = None
    ingredient_ids: list[str] = Field(default_factory=list)


class ProductRecord(RagModel):
    product_id: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)
    name: str = Field(min_length=1)
    category: ProductCategory | None = None
    texture: ProductTexture | None = None
    skin_feel: ProductSkinFeel | None = None
    ingredient_ids: list[str] = Field(default_factory=list)
    directions: str | None = Field(default=None, min_length=1)
    source_id: str = Field(min_length=1)
    checked_at: str = Field(min_length=1)
    is_demo: bool = True
```

예시 분류: `ProductCategory(code="shop:sheet-mask", name="시트 마스크")`.
예시 사용감: `ProductSkinFeel(code="shop:light", name="산뜻", aliases=["가벼운"])`.
이 값들은 검사 예시이며 실제 코드와 명칭을 강제하지 않는다. code는 같은 축 안에서
중복될 수 없고 서로 다른 공급자의 코드를 사용할 때도 충돌하지 않아야 한다.
category1/2/3의 계층 관계를 어떤 검색 코드로 제공할지는 backend·data가 정한다.

`AgentDependencies.product_taxonomy`는 필수다. backend는 `products: ProductRepository`와
같은 카탈로그를 설명하는 목록을 `AgentFactory.create`에 함께 전달한다. 저장소 클래스를
agent가 직접 import하는 방식이 아니다. 개발 조립에서도 상품 저장소만 바꾸고 분류 목록을
빠뜨리면 `ValueError`를 낸다.

`UnderstandingRequest.product_taxonomy`를 매 턴 LLM에 제공한다. `ParsedRequest`의
category/texture는 위 모델로 변경되었으며 skin_feel과 unsupported_product_conditions가
추가되었다. LLM이 코드의 이름을 바꾸면 목록의 정규 이름으로 교체하고, 없는 코드를 만들면
상품 조회 전에 미지원으로 처리한다. 알려지지 않은 자연어 조건을 탐지하는 품질은 실제 LLM
평가 대상이며 코드 목록 검증만으로 완벽한 조건 추출을 보장하지 않는다.

지원하지 않는 상품 조건은 `ChatStatus.PARTIAL`과 `UnresolvedKind.UNSUPPORTED_CONDITION`으로
반환하며 해당 상품 검색은 실행하지 않는다. backend가 `UNSUPPORTED`를 반환한 경우에도
동봉된 상품을 추천하지 않는다. 요청 조건과 실제 상품 속성은 코드로 비교한다. 이름만 같거나
속성이 `None`이면 조건 일치로 취급하지 않는다.

상품 분류 목록은 서비스 조립 시 복사하며 요청 도중 원본 객체를 바꿔 갱신하지 않는다.
목록 갱신 시 같은 히스토리와 새 목록으로 서비스를 재조립한다. 복원된 작업 조건과 후보
참조는 새 목록으로 검증하므로 폐기된 코드를 다시 조회하지 않는다. 이전 Enum 형식으로
저장된 스냅샷은 자동 변환하지 않으며 운영 전 별도 버전 전환 합의가 필요하다.

backend 요청 사항은 운영 코드/이름/별칭과 목록 버전 공급, 분류별 실제 필터 지원 범위,
명시 버전으로 상품을 찾지 못했을 때의 `NO_RESULTS` 반환이다. 제형·사용감 정보가 현재 DB에
없으면 해당 지원 목록은 비우고 상품 속성도 `None`으로 전달한다. 임의 DB 컬럼 추가는 요구하지 않는다.

## 6. main 5개 파일 제외에 따른 영향

| 제외 파일 | 기준 브랜치에서의 대응 | 남은 작업 |
| --- | --- | --- |
| `generation/prompts.py` | `generation/openai_generator.py`의 생성 프롬프트 | main의 이전 생성기 import 제거 |
| `loaders/evidence_loader.py` | `DataRecordMapper.mfds` | 조회 DTO·출처와 문서 필드 매핑 합의 |
| `loaders/knowledge_fact_loader.py` | `DataRecordMapper.knowledge` | 위와 동일; 검수 상태 보존 |
| `loaders/nia_qa_loader.py` | 대체 구현 없음 | 기존 NIA 적재 호출 제거 또는 별도 요구·계약 합의 |
| `nia_labeling_schemas.py` | 대체 구현 없음 | 라벨링 산출물 소유·필요성은 data와 합의 |

main의 `RagIngestionService`는 삭제 예정 로더 import, 동기 `pipeline.run`,
옛 `chunk.draft.ingredient_id/source_table/metadata` 필드, 원시 벡터 구조를 사용한다.
main의 `RagQueryService`는 현재 브랜치에 없는 `PerIngredientResult`와
`IngredientMentionResolution`을 참조하고 `HybridRetriever()`의 생성 방식도 다르다.
백엔드 담당자가 새 계약으로 연결해야 하며, agent 파일만 교체하면 import부터 깨질 수 있다.

## 7. 완료 판단과 검증

- 기존 인터페이스 정의와 개발용 대화 프레임은 구현되어 있다.
- agent 테스트 50개 통과: 기존 34개 + 동적 분류 10개 + RAG 계약 6개.
  실제 DB/API 및 main 통합 검증과 구분한다.
- 상품 후보의 `is_demo`는 반환 제품에서 계산하며 실제 상품 응답에는 개발용 표시를 붙이지 않는다.
  루틴 문구도 계획기의 `is_demo`를 따른다. 기본 계획기는 여전히 개발용이다.
- `ruff check agent tests`와 수정 Python 파일 포맷 검사를 통과했다. DB·네트워크 없는 데모도 실행했다.
- 동적 분류 구조와 지원 목록 주입은 반영했다. 상품/옵션/스냅샷 계약, 문서·검수 상태 매핑, backend 조회·저장 어댑터,
  운영 체크포인터는 남은 연결 항목이다.
- 현재 범위의 agent 내부 보완과 단위 검증을 완료했으며, 위 담당자 간 합의·실제 연결까지
  '전체 운영 구현·인터페이스 최종 확정'으로 보고하지 않는다.

다음 순서: 기존 계약 검토와 미정 항목 합의 → agent 타입·내부 동작 보완 및 단위 검증 →
backend 연결 수정 및 data 매핑 확인 → main 통합·DB 연동 검증.
backend와 data의 계약 검토는 지금 시작할 수 있으며 agent의 모든 기능 완성을 기다리지 않는다.
