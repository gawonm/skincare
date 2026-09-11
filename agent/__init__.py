"""에이전트 계층. 서버가 아니라 백엔드가 불러 쓰는 파이썬 패키지다.

하위 패키지

- `rag/`: 문서를 읽어 벡터로 만들고, 검색해서 답변을 만드는 파이프라인
- `tools/`: 에이전트가 호출하는 외부 도구(검색, 계산, API 호출 등)

현재 실행 진입점은 `agent.service.ChatService`이고, DB 없이 확인할 조립 코드는
`agent.factory.DevelopmentAgentFactory`에 있다. 구현 상태와 교체 지점은
`docs/agent.md`를 따른다.

`rag` 를 `agent` 안에 두는 이유: 검색 역시 에이전트가 쓰는 수단 중 하나이고,
도구가 늘어나도 백엔드가 보는 진입점은 `agent` 하나로 유지되기 때문이다.

규칙
- `backend` 를 import 하지 않는다. FastAPI 를 모른다.
- DB 세션을 스스로 만들지 않는다. 필요하면 파라미터로 받는다.
- 각 단계는 클래스로 만들고, 입력과 출력은 Enum/Pydantic 으로 정의한다.
"""
