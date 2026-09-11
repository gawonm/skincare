# 에이전트 (RAG · 챗봇)

## 구현 기준과 담당 범위

`feature/llm-rag-pipeline`의 `6f710be`를 Agent 구현 기준으로 사용해
`integration/llm-rag-main`에서 main `02ed955`를 통합한다. 아래 내용은 2026-09-11
연결 검토와 사용자 합의 결과다. DB 차원 변경과 전체 운영 저장소 조립은 아직 완료되지 않았다.

agent는 대화 해석, LangGraph 실행, 문서 청킹·임베딩, 검색 결과 통합,
근거 적용성·인용 검증, 답변 생성을 담당한다. DB 쿼리·트랜잭션·HTTP·인증 구현은
소유하지 않는다. backend가 agent의 공개 인터페이스를 구현한 어댑터를 주입한다.

## 현재 구조

| 경로 | 역할 |
| --- | --- |
| `agent/service.py` | 채팅 진입점, 권한·히스토리 계약 호출, 요청 중복 및 저장 재시도 조정 |
| `agent/factory.py` | GPT-4o mini·로컬 BGE 운영 조립, 개발용 조립과 체크포인트 직렬화 설정 |
| `agent/schemas.py`, `agent/ports.py` | 채팅·세션 입출력 모델과 외부 조회·저장 계약 |
| `agent/graph.py`, `agent/nodes.py` | LangGraph 상태 전이와 작업 처리 |
| `agent/context.py` | 제한된 LLM 문맥과 대화 요약 구성 |
| `agent/llm.py`, `agent/prompts.py` | 구조화된 의도 해석 어댑터와 프롬프트 |
| `agent/adapters.py`, `agent/demo.py` | DB 없는 개발용 저장소·모델·계획기와 실행 예제 |
| `agent/rag/schemas.py`, `agent/rag/ports.py` | RAG·상품 조회 DTO와 검색·임베딩·생성 계약 |
| `agent/rag/loaders/data_records.py` | 주입받은 데이터 DTO를 성분·근거 DTO로 변환 |
| `agent/rag/chunking/field_chunker.py` | 입력 문서의 필드 단위 청킹 및 조건 보존 |
| `agent/rag/embedding/local_embedder.py` | BGE-M3 로컬 임베딩 비동기 추론 어댑터 |
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
| `HybridSearchBackend.search` | `HybridSearchRequest` | `HybridSearchResult` |
| `EvidenceReranker.rerank` | `RerankRequest` | `RerankResult` |

위 메서드는 모두 `async`이며 호출자는 `await`해야 한다. 최상위 채팅 요청에는
`ChatService`를 사용하고, 별도 적재 배치에는 `RagIngestionPipeline`을 사용한다.
`HybridSearchBackend`의 SQLAlchemy 구현은
`backend/services/rag_search_backend.py`에 있으며 실제 DB 검증은 아직 필요하다.

`AgentFactory.create(AgentDependencies(...))`에 LLM, 히스토리, 상품·성분 조회,
상품 분류 지원 목록(`ProductTaxonomy`), 계획기, 근거 파이프라인, 체크포인터를 전달한다.
상품 분류는 코드·이름 Pydantic 모델이며 제형(`texture`)과 사용감(`skin_feel`)을 분리한다.
미등록 코드와 미상인 속성을 요청 조건에 맞는 것으로 처리하지 않는다. `DevelopmentAgentFactory`는
개발용 대체 구현을 사용한다. 운영 조립에서 이를 실제 DB 연결로 간주하지 않는다.

`ProductionAgentFactory`는 Intent·답변 생성에 `gpt-4o-mini`, 임베딩에 `BAAI/bge-m3`,
재정렬에 `BAAI/bge-reranker-v2-m3`를 연결한다. 모델 객체는 첫 사용 시 지연 로드한다.
Backend의 `AgentConfigurationAssembler`가 `config.yaml`을 운영 설정으로 변환한다.
다만 히스토리·상품·성분·루틴·체크포인터 구현이 모두 준비되지 않아
`ProductionAgentFactory`를 완성된 애플리케이션 lifespan에서 호출하는 단계는 남아 있다.

## main 통합 시 보존·제외 기준

사용자 지정에 따라 아래 main 파일과 필요한 데이터 의존성을 보존한다. agent에서
직접 import하거나 기존 시그니처를 변경하지 않는다.

- `backend/services/product_ingredient_service.py`
- `backend/repositories/product_ingredient_repository.py`
- `backend/repositories/ingredient_master_repository.py`

main의 다음 구형 파일은 최종 Agent 구성에서 제외했다. NIA 적재 기능을 대체 완료한 것으로
표시하지 않으며, data→agent 계약이 합의되기 전에는 되살리지 않는다.

- `agent/rag/embedding/openai_embedder.py`
- `agent/rag/generation/prompts.py`
- `agent/rag/loaders/evidence_loader.py`
- `agent/rag/loaders/knowledge_fact_loader.py`
- `agent/rag/loaders/nia_qa_loader.py`
- `agent/rag/nia_labeling_schemas.py`

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
- main의 `rag_chunk.embedding` 1536차원을 BGE-M3의 1024차원으로 바꾸려면 ERD 확인,
  마이그레이션, 기존 청크 전체 재임베딩을 하나의 배포 절차로 합의한다.
- OpenAI 기반으로 정한 자유 텍스트 유사도 `0.45`를 BGE-M3에 그대로 재사용하지 않고
  별도 튜닝·검증셋으로 다시 정한다.
- 애플리케이션 설정은 `config.yaml`만 사용한다. Backend가 OpenAI API 키와
  `gpt-4o-mini` 모델 설정을 읽어 `ProductionAgentConfig`에 주입하고, agent는 `.env`나
  환경변수를 직접 읽지 않는다. `.env`는 Docker Compose 변수에만 사용한다.
- 모델 캐시의 컨테이너 경로·볼륨·최초 다운로드 정책을 정하고, 재시작 때마다 가중치를
  다시 내려받지 않는지 확인한다.
- 최소 병합 게이트로 backend import/기동, 전체 단위 테스트, DB 검색·적재 통합 테스트를
  통과시킨다. 이 게이트 이후의 관측성·성능 튜닝은 후속 커밋으로 분리할 수 있다.

## 검증과 완료 범위

```sh
.venv/bin/python -m pytest tests -q -p no:cacheprovider
.venv/bin/python -m agent.demo
```

2026-09-11 agent 테스트 50개 통과를 확인했다. 기존 34개에 동적 분류 10개와 RAG 계약 6개를
추가했다. DB 없는 대화 흐름·방 격리·후보 참조·실패 복구·데이터 DTO 변환 외에도 신규 분류,
제형·사용감 분리, 폐기된 코드 차단, 조건 누락 후보 제외, 실제 상품 표시, 청킹→검색 통합→
인용·조건 검증을 검사한다. 실제 DB 검색, 임베딩 API, 운영 연결의 검증은 아니다.

동적 분류 방향은 사용자 선택으로 반영했다. 운영용 분류 코드·지원 목록의 공급,
상품 버전과 성분 스냅샷의 대응, 조회 어댑터, 실제 근거 문서 매핑·색인,
운영 히스토리·체크포인터는 아직 연결 합의가 필요하다.
현재 코드의 상세 제약과 담당자별 요청은 아래 연결 검토서가 기준이다.

## 관련 문서

- [Backend → Agent 호출 계약](../contracts/backend-to-agent.md)
- [현재 구조·연결 계약 검토](AGENT_INTEGRATION_REVIEW.md)
- [DB·히스토리 연동 요청서](RAG_YK/LLM_RAG_DB_CONTRACT.md)
- [개발 요청서](RAG_YK/LLM_RAG_DEVELOPMENT_REQUEST.md)
- [초기 파이프라인 설계](RAG_YK/LLM_RAG_PIPELINE.md)

정식 `backend → agent` 계약은 호출자인 backend가 소유하며 위 문서의 합의 내용을 따른다.
