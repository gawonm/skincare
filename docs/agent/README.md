# 에이전트 (RAG · 챗봇)

## 구현 기준과 담당 범위

`feature/llm-rag-pipeline`을 agent 구현 기준으로 사용한다. 검토 기준 커밋은
`5457e95`, 비교한 main은 `c2769bc`다. 아래 내용은 2026-09-10 연결 검토 결과이며,
백엔드·데이터 담당자와 운영 연결까지 합의하거나 통합을 완료했다는 뜻은 아니다.

agent는 대화 해석, LangGraph 실행, 문서 청킹·임베딩, 검색 결과 통합,
근거 적용성·인용 검증, 답변 생성을 담당한다. DB 쿼리·트랜잭션·HTTP·인증 구현은
소유하지 않는다. backend가 agent의 공개 인터페이스를 구현한 어댑터를 주입한다.

## 현재 구조

| 경로 | 역할 |
| --- | --- |
| `agent/service.py` | 채팅 진입점, 권한·히스토리 계약 호출, 요청 중복 및 저장 재시도 조정 |
| `agent/factory.py` | 의존성 주입, 그래프 조립, 개발용 조립과 체크포인트 직렬화 설정 |
| `agent/schemas.py`, `agent/ports.py` | 채팅·세션 입출력 모델과 외부 조회·저장 계약 |
| `agent/graph.py`, `agent/nodes.py` | LangGraph 상태 전이와 작업 처리 |
| `agent/context.py` | 제한된 LLM 문맥과 대화 요약 구성 |
| `agent/llm.py`, `agent/prompts.py` | 구조화된 의도 해석 어댑터와 프롬프트 |
| `agent/adapters.py`, `agent/demo.py` | DB 없는 개발용 저장소·모델·계획기와 실행 예제 |
| `agent/rag/schemas.py`, `agent/rag/ports.py` | RAG·상품 조회 DTO와 검색·임베딩·생성 계약 |
| `agent/rag/loaders/data_records.py` | 주입받은 데이터 DTO를 성분·근거 DTO로 변환 |
| `agent/rag/chunking/field_chunker.py` | 입력 문서의 필드 단위 청킹 및 조건 보존 |
| `agent/rag/embedding/openai_embedder.py` | 설정을 주입받는 비동기 임베딩 호출 |
| `agent/rag/retrieval/` | 성분명 해석, 질문 의도 분류, 하이브리드 검색 결과 통합 |
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

위 메서드는 모두 `async`이며 호출자는 `await`해야 한다. 최상위 채팅 요청에는
`ChatService`를 사용하고, 별도 적재 배치에는 `RagIngestionPipeline`을 사용한다.
`HybridSearchBackend`는 실제 DB 조회 구현이 필요한 추상 계약이다.

`AgentFactory.create(AgentDependencies(...))`에 LLM, 히스토리, 상품·성분 조회,
상품 분류 지원 목록(`ProductTaxonomy`), 계획기, 근거 파이프라인, 체크포인터를 전달한다.
상품 분류는 코드·이름 Pydantic 모델이며 제형(`texture`)과 사용감(`skin_feel`)을 분리한다.
미등록 코드와 미상인 속성을 요청 조건에 맞는 것으로 처리하지 않는다. `DevelopmentAgentFactory`는
개발용 대체 구현을 사용한다. 운영 조립에서 이를 실제 DB 연결로 간주하지 않는다.

## main 통합 시 보존·제외 기준

사용자 지정에 따라 아래 main 파일과 필요한 데이터 의존성을 보존한다. agent에서
직접 import하거나 기존 시그니처를 변경하지 않는다.

- `backend/services/product_ingredient_service.py`
- `backend/repositories/product_ingredient_repository.py`
- `backend/repositories/ingredient_master_repository.py`

main에만 있는 다음 5개 파일은 최종 agent 구성에서 제외하는 방향으로 정리한다.
현재 agent 브랜치에는 원래 없으므로 이번 문서 수정으로 삭제된 파일은 없다.
main의 호출부 정리와 함께 통합해야 하며, NIA 적재 기능을 대체 완료한 것으로 표시하지 않는다.

- `agent/rag/generation/prompts.py`
- `agent/rag/loaders/evidence_loader.py`
- `agent/rag/loaders/knowledge_fact_loader.py`
- `agent/rag/loaders/nia_qa_loader.py`
- `agent/rag/nia_labeling_schemas.py`

충돌 9개 파일도 현재 브랜치를 기준으로 검토한다. 파일이 충돌하지 않았더라도
main의 RAG 서비스·테스트가 이전 DTO를 참조하면 연결 수정 대상이다.

## 검증과 완료 범위

```sh
.venv/bin/python -m pytest tests -q -p no:cacheprovider
.venv/bin/python -m agent.demo
```

2026-09-10 agent 테스트 50개 통과를 확인했다. 기존 34개에 동적 분류 10개와 RAG 계약 6개를
추가했다. DB 없는 대화 흐름·방 격리·후보 참조·실패 복구·데이터 DTO 변환 외에도 신규 분류,
제형·사용감 분리, 폐기된 코드 차단, 조건 누락 후보 제외, 실제 상품 표시, 청킹→검색 통합→
인용·조건 검증을 검사한다. 실제 DB 검색, 임베딩 API, 운영 연결의 검증은 아니다.

동적 분류 방향은 사용자 선택으로 반영했다. 운영용 분류 코드·지원 목록의 공급,
상품 버전과 성분 스냅샷의 대응, 조회 어댑터, 실제 근거 문서 매핑·색인,
운영 히스토리·체크포인터는 아직 연결 합의가 필요하다.
현재 코드의 상세 제약과 담당자별 요청은 아래 연결 검토서가 기준이다.

## 관련 문서

- [현재 구조·연결 계약 검토](RAG_YK/AGENT_INTEGRATION_REVIEW.md)
- [DB·히스토리 연동 요청서](RAG_YK/LLM_RAG_DB_CONTRACT.md)
- [개발 요청서](RAG_YK/LLM_RAG_DEVELOPMENT_REQUEST.md)
- [초기 파이프라인 설계](RAG_YK/LLM_RAG_PIPELINE.md)

정식 `backend → agent` 계약은 호출자인 backend가 `docs/contracts/backend-to-agent.md`에
초안을 작성하고 agent와 합의한다. 이 README와 검토서는 그 초안에 사용할 현재 구현 정보를
제공하며 합의 자체를 대신하지 않는다.
