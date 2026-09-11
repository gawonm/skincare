# 백엔드 (FastAPI · 업무 로직)

## Agent 통합

- `agent_configuration.py`: `config.yaml`의 OpenAI·로컬 모델·검색 설정을 Agent Pydantic
  설정으로 변환한다.
- `rag_search_backend.py`: repository의 pgvector/BM25 결과를 현재 Agent 검색 DTO로 변환한다.
- `rag_ingestion_service.py`: DB 트랜잭션을 유지하면서 현재 비동기 로컬 임베딩 파이프라인을
  호출한다.

구형 `RagQueryService`와 `OpenAiEmbedder` 경로는 사용하지 않는다. 사용자 질의의 최종 진입점은
Agent의 `ChatService.handle_turn`이며, 히스토리·상품·성분·루틴·체크포인터 운영 구현은 아직
연결해야 한다.

## 관련 문서

- [Backend → Agent 호출 계약](../contracts/backend-to-agent.md)
- [Agent 통합 검토](../agent/AGENT_INTEGRATION_REVIEW.md)
