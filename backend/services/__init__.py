"""엔드포인트와 나머지 계층 사이를 잇는 업무 로직 계층.

`agent` 패키지 호출, `repositories` 를 통한 저장, 트랜잭션 경계(commit/rollback)를
여기서 정한다.

SQLAlchemy 쿼리를 직접 쓰지 않는다. DB 접근은 `repositories/` 에 맡긴다.
"""
