# 에이전트 (RAG · 챗봇)

## 구현 기준과 담당 범위

`feature/llm-rag-pipeline`의 `6f710be`를 Agent 구현 기준으로 사용해
`integration/llm-rag-main`에서 main `02ed955`를 통합한다. 아래 내용은 2026-09-11
연결 검토와 사용자 합의 결과다. 기존 DB 차원은 유지하며 전체 운영 저장소 조립은 아직
완료되지 않았다.

agent는 대화 해석, LangGraph 실행, 문서 청킹·임베딩, 검색 결과 통합,
근거 적용성·인용 검증, 답변 생성을 담당한다. DB 쿼리·트랜잭션·HTTP·인증 구현은
소유하지 않는다. backend가 agent의 공개 인터페이스를 구현한 어댑터를 주입한다.

## 현재 구조

| 경로 | 역할 |
| --- | --- |
| `agent/service.py` | 채팅 진입점, 권한·히스토리 계약 호출, 요청 중복 및 저장 재시도 조정 |
| `agent/factory.py` | 채팅 모델·BGE-M3 임베딩·로컬 BGE 리랭커 운영 조립과 개발용 조립 |
| `agent/schemas.py`, `agent/ports.py` | 채팅·세션 입출력 모델과 외부 조회·저장 계약 |
| `agent/graph.py`, `agent/nodes.py` | LangGraph 상태 전이와 작업 처리 |
| `agent/rag_workflow.py`, `agent/rag_response.py` | Claim 탐색→Evidence 검증 노드와 분리된 응답 조립 |
| `agent/runtime.py`, `agent/task_planning.py` | 실행 정책과 Intent 의존성 순서 |
| `agent/context.py` | 제한된 LLM 문맥과 대화 요약 구성 |
| `agent/llm.py`, `agent/prompts.py` | 구조화된 의도 해석 어댑터와 프롬프트 |
| `agent/adapters.py`, `agent/demo.py` | DB 없는 개발용 저장소·모델·계획기와 실행 예제 |
| `agent/rag/schemas.py`, `agent/rag/ports.py` | RAG·상품 조회 DTO와 검색·임베딩·생성 계약 |
| `agent/rag/claim_schemas.py` | NIA Claim 전용 DTO와 성분 anchor 계약 |
| `agent/rag/loaders/data_records.py` | 주입받은 데이터 DTO를 성분·근거 DTO로 변환 |
| `agent/rag/chunking/field_chunker.py` | 입력 문서의 필드 단위 청킹 및 조건 보존 |
| `agent/rag/embedding/` | 선택형 OpenAI·BGE-M3 비동기 임베딩 어댑터와 조립 팩토리 |
| `agent/rag/retrieval/` | 성분명 해석, 의도 분류, 하이브리드 검색 통합 및 BGE 리랭커 |
| `agent/rag/generation/` | 문장별 인용과 조건 검사, 생성 모델 어댑터 |
| `agent/rag/pipeline.py` | 적재용 청킹·임베딩과 질의용 검색·적용성·생성 조립 |

`DataRecordMapper`는 DB나 CSV를 읽지 않으며 `EvidenceRecord`를 반환한다.
`RagIngestionPipeline`은 `RagDocument`를 받는다. 두 타입 사이에서 어떤 원문 필드를
청킹할지는 데이터 계약으로 합의해야 한다. 원문·출처·검수 상태를 임의로 채우지 않는다.

## 공개 진입점

| 호출 | 입력 | 출력 |
| --- | --- | --- |
| `ChatService.handle_turn` | `ChatServiceRequest` | `ChatTurnOutput` |
| `RagIngestionPipeline.run` | `list[RagDocument]` | `list[EmbeddedChunk]` |
| `EvidencePipeline.run` | `EvidenceSearchRequest` | `EvidenceBundle` |
| `ClaimRetriever.search` | `ClaimSearchRequest` | `ClaimSearchResult` |
| `HybridSearchBackend.search` | `HybridSearchRequest` | `HybridSearchResult` |
| `EvidenceReranker.rerank` | `RerankRequest` | `RerankResult` |

위 메서드는 모두 `async`이며 호출자는 `await`해야 한다. 최상위 채팅 요청에는
`ChatService`를 사용하고, 별도 적재 배치에는 `RagIngestionPipeline`을 사용한다.
`HybridSearchBackend`의 SQLAlchemy 구현은
`backend/services/rag_search_backend.py`에 있으며 실제 DB 검증은 아직 필요하다.

`AgentFactory.create(AgentDependencies(...))`에 LLM, 히스토리, 상품·성분 조회,
상품 분류 지원 목록(`ProductTaxonomy`), 계획기, Claim 검색기, 근거 파이프라인, 체크포인터를 전달한다.
상품 분류는 코드·이름 Pydantic 모델이며 제형(`texture`)과 사용감(`skin_feel`)을 분리한다.
미등록 코드와 미상인 속성을 요청 조건에 맞는 것으로 처리하지 않는다. `DevelopmentAgentFactory`는
개발용 대체 구현을 사용한다. 운영 조립에서 이를 실제 DB 연결로 간주하지 않는다.

`ProductionAgentFactory`는 채팅 모델과 별개로 운영 임베딩을 `BAAI/bge-m3` 1024차원으로
고정하고, 재정렬에 `BAAI/bge-reranker-v2-m3`를 연결한다. `ProductionAgentConfig`는 OpenAI
임베딩을 거부하며, 주입된 `ClaimRetriever`도 BGE-M3 색인을 사용한다고 명시해야 한다.
로컬 모델 객체는 첫 사용 시 지연 로드한다.
Backend의 `AgentConfigurationAssembler`가 `config.yaml`을 운영 설정으로 변환한다.
현재 Backend의 1536차원 OpenAI 설정은 새 Agent 계약과 맞지 않으므로 운영 연결 전에
BGE-M3 설정·DB 차원·재임베딩 합의가 필요하다. 또한 히스토리·상품·성분·Claim 검색·
루틴·체크포인터 구현이 모두 준비되지 않아
`ProductionAgentFactory`를 완성된 애플리케이션 lifespan에서 호출하는 단계는 남아 있다.

## main 통합 시 보존·제외 기준

사용자 지정에 따라 아래 main 파일과 필요한 데이터 의존성을 보존한다. agent에서
직접 import하거나 기존 시그니처를 변경하지 않는다.

- `backend/services/product_ingredient_service.py`
- `backend/repositories/product_ingredient_repository.py`
- `backend/repositories/ingredient_master_repository.py`

main의 다음 구형 파일은 최종 Agent 구성에서 제외했다. NIA 적재 기능을 대체 완료한 것으로
표시하지 않으며, data→agent 계약이 합의되기 전에는 되살리지 않는다.

- `agent/rag/generation/prompts.py`
- `agent/rag/loaders/evidence_loader.py`
- `agent/rag/loaders/knowledge_fact_loader.py`
- `agent/rag/loaders/nia_qa_loader.py`
- `agent/rag/nia_labeling_schemas.py`

main의 동기식 구형 `OpenAiEmbedder` 구현은 제거했고, 같은 경로에는 현재 `TextEmbedder` 비동기
계약을 구현하는 `OpenAiTextEmbedder`를 새로 연결했다.

최신 main을 현재 기능 브랜치에 병합하면 아래 8개 파일에서 실제 텍스트 충돌이 발생한다.
Git은 충돌을 해결하기 전에는 병합 커밋을 완료할 수 없다. 따라서 **main을 기능 브랜치에 먼저
병합하고 충돌을 해결한 뒤 검증하는 방향**은 가능하지만, 기능 브랜치를 main에 먼저 병합해
깨진 상태를 후속 수정하는 방향은 허용하지 않는다.

- `agent/rag/chunking/field_chunker.py`
- `agent/rag/generation/answer_generator.py`
- `agent/rag/generation/condition_preservation_checker.py`
- `agent/rag/pipeline.py`
- `agent/rag/retrieval/hybrid_retriever.py`
- `agent/rag/retrieval/ingredient_mention_resolver.py`
- `agent/rag/retrieval/question_intent_classifier.py`
- `agent/rag/schemas.py`

충돌하지 않은 파일도 main의 RAG 서비스·테스트가 이전 DTO를 참조하면 연결 수정 대상이다.
한쪽 파일 전체를 선택하는 방식으로 해결하면 main의 DB 계약이나 현재 agent 계약 중 하나가
사라지므로 각 공개 타입과 호출부를 함께 확인한다.

## Backend 담당자 확인 항목

main 반영 전에 최소한 다음 항목은 완료해야 한다. 세부 근거와 후속 항목은
[연결 계약 검토](AGENT_INTEGRATION_REVIEW.md#7-backend-병합-확인-체크리스트)에 있다.

- `ChatService.handle_turn`을 호출할 API/service와 `ProductionAgentFactory` 생성 위치를 정한다.
- `ProductionAgentDependencies`의 히스토리·상품·성분·루틴·검색·체크포인터 구현을 주입한다.
- 구형 `RagQueryService`는 제거했고 `RagIngestionService`는 현재 비동기 포트로 전환했다.
- `SqlAlchemyHybridSearchBackend.search`가 target 필터, vector/BM25 원점수, 상태 코드와
  후보 개수 계약을 구현한다. 실제 DB 통합 테스트는 아직 필요하다.
- Agent가 요구하는 BGE-M3 1024차원에 맞춰 질의·적재 모델과 `embedding_model` 값을 통일한다.
- BGE-M3의 1024차원에 맞춘 ERD 갱신(`docs/erd/app.md`), 마이그레이션,
  기존 65,196건 청크(특히 DB 원본 테이블이 없는 `nia_qa` 45,002건 유실 방지를 위한 content 인플레이스
  UPDATE) 재임베딩과 별도 유사도 임계값 검증을 진행한다.
  Agent 계층은 `LocalBgeM3Embedder`와 1024차원 조립을 제공하며, Backend/Data 파트는 설정 주입과
  DB 전환을 담당한다. 현재 Backend 설정은 아직 이 계약으로 전환되지 않았다.
- 애플리케이션 설정은 `config.yaml`만 사용한다. Backend가 OpenAI API 키와
  `gpt-4o-mini` 모델 설정을 읽어 `ProductionAgentConfig`에 주입하고, agent는 `.env`나
  환경변수를 직접 읽지 않는다. `.env`는 Docker Compose 변수에만 사용한다.
- 로컬 리랭커와 선택적 로컬 임베더의 모델 캐시 경로·볼륨·최초 다운로드 정책을 정하고,
  재시작 때마다 가중치를 다시 내려받지 않는지 확인한다.
- 최소 병합 게이트로 backend import/기동, 전체 단위 테스트, DB 검색·적재 통합 테스트를
  통과시킨다. 이 게이트 이후의 관측성·성능 튜닝은 후속 커밋으로 분리할 수 있다.

## 검증과 완료 범위

```sh
uv run pytest tests/agent -q
uv run pytest tests -q
uv run python -m agent.demo
```

2026-09-17 Agent 테스트 116개와 프로젝트 전체 테스트 186개 통과를 확인했다. DB 없는 대화 흐름·방 격리·
후보 참조·실패 복구·데이터
DTO 변환 외에도 신규 분류,
제형·사용감 분리, 폐기된 코드 차단, 조건 누락 후보 제외, 실제 상품 표시, 청킹→검색 통합→
인용·조건 검증, Claim→Evidence 라우팅, 복합 Claim 방어와 동일 상품 병합을 검사한다. 실제 Claim DB 검색, 운영 BGE-M3 모델 로딩,
임베딩 API, 운영 연결의 검증은 아니다.

동적 분류 방향은 사용자 선택으로 반영했다. 운영용 분류 코드·지원 목록의 공급,
상품 버전과 성분 스냅샷의 대응, 조회 어댑터, 실제 근거 문서 매핑·색인,
운영 히스토리·체크포인터는 아직 연결 합의가 필요하다.
현재 코드의 상세 제약과 담당자별 요청은 아래 연결 검토서가 기준이다.

## 관련 문서

- [2026-09-17 17:51 피부 고민형 Intent 라우팅 보정](2026-09-17_1751_INTENT_ROUTING_UPDATE.md)
- [2-Layer RAG Agent 리팩터링 작업계획](TWO_LAYER_RAG_REFACTOR_PLAN.md)
- [2-Layer RAG Agent 후속 보완 작업계획](TWO_LAYER_RAG_FOLLOWUP_PLAN.md)
- [2-Layer RAG Agent — main 대비 변경점](TWO_LAYER_RAG_MAIN_DIFF.md)
- [Backend → Agent 호출 계약](../contracts/backend-to-agent.md)
- [현재 구조·연결 계약 검토](AGENT_INTEGRATION_REVIEW.md)
- [DB·히스토리 연동 요청서](RAG_YK/LLM_RAG_DB_CONTRACT.md)
- [개발 요청서](RAG_YK/LLM_RAG_DEVELOPMENT_REQUEST.md)
- [초기 파이프라인 설계](RAG_YK/LLM_RAG_PIPELINE.md)

정식 `backend → agent` 계약은 호출자인 backend가 소유하며 위 문서의 합의 내용을 따른다.

## Evidence RAG 검수 상태 계약 보류 (2026-09-17)

현재 Evidence RAG의 저장·검수 계약은 아직 확정하지 않았다. Agent는 저장소의 원시 상태 문자열을
직접 해석하지 않고, Backend가 변환한 `EvidenceReviewStatus`만 사용한다.

- `VERIFIED`: 검수 완료로 합의된 저장 상태만 변환 대상이다. Citation과 `SUPPORTED` 판정에
  사용할 수 있다.
- `UNREVIEWED`: 검색 결과에는 남기지만 Citation과 `SUPPORTED` 판정에는 사용하지 않는다.
  연결된 Claim은 `INSUFFICIENT`가 되며, 명시적 상반·오류가 아니라면 `CLAIM_ONLY` 탐색 후보로
  유지한다.
- `evidence_level=peer_reviewed_study`는 자료 유형·근거 등급이지 사람 검수 완료 상태가 아니다.
  이 값만으로 `VERIFIED`로 승격하지 않는다.

최신 `skincare_latest` dump의 `evidence_document.document_status` 허용값은 `final`,
`amended_final`, `tentative`, `draft`, `rereview`, `unknown`, `NULL`이다. 현재 세 PubMed 행은
`NULL`이므로 Agent에서 모두 `UNREVIEWED`로 보이는 것이 정상이다.

현재 Backend 어댑터가 확인하는 문자열 `verified`는 dump의 CHECK 제약조건에 존재하지 않아 실제로
성립할 수 없다. 이는 Evidence RAG 계약 확정 전의 임시 매핑이며, 운영 가능한 검수 상태 계약으로
간주하지 않는다. Evidence RAG 구현을 이어갈 때 Data 파트와 아래 중 하나를 먼저 합의한다.

1. `final`/`amended_final` 중 어떤 값이 사람 검수 완료를 의미하는지 확정하고 Backend 매핑을 수정한다.
2. `document_status`가 문서 생명주기만 나타낸다면 별도 `review_status`를 ERD·마이그레이션에 추가한다.

합의 전에는 Agent의 검수 게이트를 완화하거나 PubMed 자료를 자동으로 `VERIFIED` 처리하지 않는다.
계약이 확정되면 `docs/contracts/backend-to-agent.md`, Agent 회귀 테스트, 실제 DB smoke 결과를 함께
갱신한다.
