# 백엔드 (FastAPI · 업무 로직)

## Agent 통합

- `agent_configuration.py`: `config.yaml`의 OpenAI·로컬 모델·검색 설정을 Agent Pydantic
  설정으로 변환하고 선택한 임베딩 출력 차원이 현재 DB의 1536차원과 같은지 검증한다. OpenAI
  검색 임계값을 생략하면 기존 검증값 `0.45`를 사용한다.
- `rag_search_backend.py`: repository의 pgvector/BM25 결과를 현재 Agent 검색 DTO로 변환한다.
- `rag_ingestion_service.py`: DB 트랜잭션을 유지하면서 설정에서 선택한 비동기 임베딩 파이프라인을
  호출한다.

구형 `RagQueryService`와 동기식 `OpenAiEmbedder`는 사용하지 않는다. 현재 운영 임베더는
비동기 `OpenAiTextEmbedder`이며 사용자 질의의 최종 진입점은 Agent의
`ChatService.handle_turn`이다. 히스토리·상품·성분·루틴·체크포인터 운영 구현은 아직 연결해야
한다.

## 관련 문서

- [Backend → Agent 호출 계약](../contracts/backend-to-agent.md)
- [Agent 통합 검토](../agent/AGENT_INTEGRATION_REVIEW.md)
