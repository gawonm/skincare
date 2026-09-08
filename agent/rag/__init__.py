"""RAG 파이프라인. `agent` 가 쓰는 검색·답변 생성 수단이다.

단계별로 폴더를 나눈다. "답변이 이상하다"는 문제가 어느 단계에서 생겼는지
따로 확인하고 테스트할 수 있게 하기 위해서다.

    loaders -> chunking -> embedding -> retrieval -> generation

규칙
- `backend`를 import 하지 않는다. FastAPI 를 모른다.
- DB 세션을 스스로 만들지 않는다. 필요하면 파라미터로 받는다.
- 각 단계는 클래스로 만들고, 입력과 출력은 Enum/Pydantic 으로 정의한다.
"""
