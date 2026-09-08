"""FastAPI 애플리케이션. HTTP 요청과 응답만 담당한다.

계층 순서

    api  ->  services  ->  repositories  ->  models
                  └────->  agent

규칙
- 에이전트/RAG 로직을 여기에 직접 쓰지 않는다. `agent` 패키지를 호출한다.
- 엔드포인트 함수는 얇게 유지하고, 실제 처리는 `services/` 의 클래스에 맡긴다.
- SQLAlchemy 쿼리는 `repositories/` 에만 둔다.

의존: `agent`, `models`, `core` 를 import 한다. 반대 방향은 없다.
"""
