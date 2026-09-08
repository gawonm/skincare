"""여러 계층이 함께 쓰는 Enum과 Pydantic 모델.

`backend`와 `agent`가 모두 참조하는 타입만 여기에 둔다. 한쪽에서만 쓰는 타입은
그 계층 안(`agent/rag/schemas.py`, `backend/schemas/`)에 둔다.

이 모듈은 다른 계층을 import 하지 않는다.
"""
