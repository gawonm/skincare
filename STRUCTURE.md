# 폴더 구조

```
skincare/
├── core/                  # 공용 인프라. 설정, DB 연결, Redis
│   ├── config.py
│   ├── database.py
│   ├── redis.py
│   └── types.py           # 여러 계층이 함께 쓰는 Enum/Pydantic
├── models/                # SQLAlchemy 테이블 정의
├── migrations/            # Alembic 마이그레이션
├── agent/                 # 에이전트 계층 (서버 아님, 파이썬 패키지)
│   ├── rag/               #   RAG 파이프라인
│   │   ├── schemas.py     #     RAG 입출력 Enum/Pydantic
│   │   ├── loaders/       #     문서 읽기
│   │   ├── chunking/      #     텍스트 자르기
│   │   ├── embedding/     #     벡터화
│   │   ├── retrieval/     #     검색 (pgvector + pg_search)
│   │   ├── generation/    #     LLM 답변 생성
│   │   └── pipeline.py    #     위 단계를 순서대로 조립
│   └── tools/             #   에이전트가 호출하는 도구
├── backend/               # FastAPI. HTTP 담당
│   ├── main.py            #   앱 생성과 lifespan (진입점)
│   ├── api/               #   엔드포인트
│   ├── schemas/           #   요청/응답 Pydantic
│   ├── services/          #   업무 로직. agent 호출 + 트랜잭션
│   └── repositories/      #   DB 조회/저장 쿼리
├── frontend/              # 아직 미정
├── scripts/               # 일회성 데이터 적재/ETL. 원본 파일 → models/ 테이블
├── examples/models/       # 모델 작성 예시 (참고용)
└── tests/
```

## 의존 방향

```
frontend  →  backend  →  agent  →  core
                 └──────────────→  models
```

backend 안에서도 순서가 있다.

```
api  →  services  →  repositories  →  models
            └─────→  agent
```

agent 안에서도 순서가 있다.

```
rag  →  core
tools  →  core
```

화살표 방향으로만 import 한다. 반대 방향은 없다.

- `core` 는 아무것도 import 하지 않는다. 제일 아래층이다.
- `agent` 는 `backend` 를 import 하지 않는다. FastAPI 를 모른다.
- `agent` 는 DB 세션을 직접 만들지 않는다. 필요하면 파라미터로 받는다.
- `rag` 를 `agent` 안에 두는 이유: 검색도 에이전트가 쓰는 수단 중 하나다. 도구가 늘어나도
  `backend` 가 보는 진입점은 `agent` 하나로 유지된다.
- `models` 를 루트에 두는 이유: `backend` 와 `agent` 가 모두 테이블을 읽기 때문이다.
  한쪽 안에 두면 반대쪽이 상대를 import 하게 되어 방향이 꺾인다.
- SQLAlchemy 쿼리는 `repositories/` 에만 쓴다. `api/` 와 `services/` 에서는 쓰지 않는다.
- commit 은 `services/` 에서만 한다. 리포지토리는 조회와 저장만 하고 트랜잭션을 끝내지 않는다.
- `scripts/` 는 웹 요청 경로(`backend`)나 에이전트 도구(`agent/tools`)와 분리된 일회성
  데이터 적재용이다. PDF·엑셀 등 원본 파일을 파싱해 `models/` 테이블에 적재하는 코드가
  여기 들어간다. `core`, `models` 만 import 하고 `backend`, `agent` 는 import 하지 않는다.

## 새 모델을 추가할 때

1. `models/` 에 파일을 만든다.
2. `config.yaml` 의 `database.model_modules` 에 모듈 경로를 추가한다.
3. `just makemigrations "설명"` 으로 리비전을 만든다.
4. 생성된 파일 내용을 확인한 뒤 `just migrate upgrade head` 를 실행한다.

2번을 빠뜨리면 모델이 metadata 에 올라오지 않아 마이그레이션에 아무것도 나오지 않는다.
