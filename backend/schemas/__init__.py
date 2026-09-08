"""HTTP 요청과 응답에 쓰는 Pydantic 모델.

`models/` 의 SQLAlchemy 테이블을 그대로 응답으로 내보내지 않는다.
내부 컬럼이 외부에 노출되고, 테이블을 바꾸면 API 가 같이 깨지기 때문이다.
"""
