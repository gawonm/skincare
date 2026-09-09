# 코드 작성 규칙

## 1. 클래스 기반 작성

모든 코드는 클래스 기반으로 작성한다.

- 기능 단위는 모듈 레벨 함수가 아니라 클래스의 메서드로 구현한다.
- 상태와 동작은 하나의 클래스 안에 묶는다.
- 전역 변수, 전역 함수로 로직을 흩뿌리지 않는다.

## 2. 타입 정의는 enum / Pydantic 기반

함수·메서드의 파라미터와 반환값에 사용하는 타입은 `enum` 또는 Pydantic 모델로 정의한다.

- 고정된 값의 집합은 `Enum`(또는 `StrEnum`)으로 정의하고, 문자열 리터럴을 직접 쓰지 않는다.
- 구조화된 데이터는 Pydantic 모델로 정의하고, `dict`나 튜플을 그대로 주고받지 않는다.
- 컬렉션은 Pydantic 모델을 원소로 하는 제네릭 형태로 명시한다.
  - `list[SomeModel]`
  - `dict[str, SomeModel]`
  - `dict[SomeEnum, list[SomeModel]]`
- 파라미터와 반환값 모두에 타입 힌트를 빠짐없이 붙인다.

## 3. 불확실한 내용은 임의로 결정하지 않는다

작업 도중 확실하지 않은 부분이 나오면 임의로 판단해서 진행하지 말고, 반드시 사용자에게 질문하여 선택을 받는다.

질문할 때는 다음을 쉽고 자세하게 함께 설명한다.

- 왜 이 선택이 필요한지 (어떤 부분이 불명확한지)
- 각 선택지가 어떤 결과를 가져오는지 (장단점, 영향 범위)
- 추천하는 선택지가 있다면 그 이유

사용자의 답변을 받기 전까지 해당 부분은 진행하지 않는다.

## 4. 주석은 한국어로, "왜"를 적는다

코드만 봐도 아는 내용은 주석으로 쓰지 않는다. 왜 이렇게 했는지를 적는다.

```python
# 나쁨: 무엇을 하는지만 적음
# 리스트를 순회한다
for item in items:
    ...

# 좋음: 이유를 적음
# 순서가 뒤섞이면 마이그레이션이 깨지므로 정렬된 상태로만 순회한다
for item in sorted(items):
    ...
```

## 5. 코드를 바꾼 뒤에는 설명한다

파일을 수정하면 세 줄 정도로 요약해서 알려준다.

- 무엇을 바꿨는지
- 왜 바꿨는지
- 사용자가 확인해야 할 것이 있는지

## 6. 새 라이브러리는 먼저 물어본다

의존성을 추가하기 전에 아래를 설명하고 허락을 받는다.

- 왜 필요한지
- 없이도 되는지, 안 된다면 그 이유

## 7. 에러를 숨기지 않는다

- `except: pass`, 내용이 빈 `try` 블록은 쓰지 않는다.
- 예외를 잡을 때는 잡을 예외 종류를 명시하고, 무엇이 잘못됐는지 알 수 있는 메시지를 남긴다.

```python
# 나쁨: 실패해도 아무도 모른다
try:
    connect_db()
except:
    pass

# 좋음: 무엇이 왜 실패했는지 드러난다
try:
    connect_db()
except ConnectionError as e:
    raise RuntimeError(f"DB 연결 실패: {e}") from e
```

## 8. 요청한 것만 한다

- 요청 범위 밖의 리팩터링, 파일 정리, 이름 변경은 하지 않는다.
- 고칠 만한 부분을 발견하면 직접 고치지 말고 먼저 알려준다.

## 9. 매직 넘버와 매직 문자열을 쓰지 않는다

의미 있는 값은 이름을 붙여서 상수나 `Enum`으로 뺀다. (규칙 2와 같은 맥락)

```python
# 나쁨: 30이 무슨 뜻인지 알 수 없다
if retry_count > 30:
    ...
if status == "done":
    ...

# 좋음
MAX_RETRY_COUNT = 30

class TaskStatus(StrEnum):
    DONE = "done"

if retry_count > MAX_RETRY_COUNT:
    ...
if status is TaskStatus.DONE:
    ...
```

## 10. 정해진 폴더 구조를 지킨다

전체 구조와 각 폴더의 역할은 `STRUCTURE.md`에 있다. 새 파일은 그 구조 안에 만든다.

| 폴더 | 넣는 것 | 넣지 않는 것 |
| --- | --- | --- |
| `core/` | 설정, DB 연결, Redis, 공용 타입 | 업무 로직 |
| `models/` | SQLAlchemy 테이블 정의 | 업무 로직, API 응답용 모델 |
| `agent/rag/` | 문서 로딩·자르기·임베딩·검색·답변 생성 | FastAPI 코드, HTTP 관련 코드 |
| `agent/tools/` | 에이전트가 호출하는 도구 | FastAPI 코드, HTTP 관련 코드 |
| `backend/api/` | 엔드포인트 | 업무 로직, DB 쿼리 |
| `backend/schemas/` | 요청/응답 Pydantic 모델 | 테이블 정의 |
| `backend/services/` | 업무 로직, agent 호출, 트랜잭션 | SQLAlchemy 쿼리 |
| `backend/repositories/` | DB 조회/저장 쿼리 | 업무 로직, commit |
| `frontend/` | 화면 코드 | 파이썬 코드 |

새 폴더가 필요해 보이면 만들기 전에 먼저 물어본다.

## 11. import 방향을 지킨다

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

화살표 방향으로만 import 한다. 반대 방향으로 import 하면 두 폴더가 서로를 필요로 하게 되어,
한쪽만 떼어내 테스트하거나 수정할 수 없게 된다.

- `core`는 아무것도 import 하지 않는다.
- `agent`는 `backend`를 import 하지 않는다. FastAPI를 몰라야 한다.
- `agent`는 DB 세션을 직접 만들지 않는다. 필요하면 파라미터로 받는다.

## 12. DB 접근은 리포지토리에만 쓴다

SQLAlchemy 쿼리(`select`, `insert` 등)는 `backend/repositories/` 안에서만 작성한다.
엔드포인트나 서비스에 쿼리를 직접 쓰지 않는다.

- 테이블 하나당 리포지토리 클래스 하나로 만든다.
- 세션은 생성자에서 주입받는다. 리포지토리가 직접 만들지 않는다.
- 반환은 SQLAlchemy 모델 또는 Pydantic 모델로 한다. dict, 튜플로 내보내지 않는다.
- `commit`은 리포지토리에서 하지 않는다. 언제 확정할지는 `services/`가 정한다.

이렇게 나누면 같은 조회가 여러 곳에 다르게 복사되는 일이 없고, 쿼리를 고칠 때 한 파일만 보면 된다.

## 13. 모델을 추가하면 설정도 같이 고친다

`models/`에 새 파일을 만들면 `config.yaml`의 `database.model_modules`에 모듈 경로를 반드시 추가한다.
빠뜨리면 Alembic이 모델을 인식하지 못해 마이그레이션에 아무 변경도 나오지 않는다.
원인을 찾기 어려운 실수라 항상 같이 확인한다.

## 14. 개발 플로우는 SETUP.md를 따른다

명령과 실행 순서의 정본은 `SETUP.md`다. 이 문서는 "어떻게 쓰는가"만 요약한다.
헷갈리면 `SETUP.md`를 열어서 확인하고, 두 문서가 어긋나면 `SETUP.md`가 맞는 것으로 본다.

### 처음 한 번만 하는 것

`SETUP.md`의 "2. 최초 1회 준비"를 순서대로 따른다. 요약하면 다섯 단계다.

1. `uv sync --dev` — 파이썬 패키지를 깔고 `.venv`를 만든다.
2. `uv run pre-commit install` — 커밋 전 자동 검사를 건다.
3. `config.yaml.sample` 을 `config.yaml` 로, `.env.example` 을 `.env` 로 복사한다.
   `config.yaml` 은 `.gitignore` 에 들어 있어 커밋되지 않는다.
4. `just up` — PostgreSQL 과 Redis 컨테이너를 켜고 준비될 때까지 기다린다.
5. `just migrate upgrade head` — 테이블을 만든다.

### 매일 개발할 때

```bash
just up        # 컨테이너 켜기
just server    # FastAPI 개발 서버 (파일이 바뀌면 자동 재시작)
just down      # 다 하면 컨테이너 끄기
```

`just down` 은 컨테이너만 멈춘다. DB 안의 데이터는 그대로 남으므로 매일 반복해도 안전하다.

### 모델을 바꿨을 때

가장 자주 밟는 흐름이다. 순서를 지키지 않으면 마이그레이션이 비거나 깨진다.

1. `models/` 에 파일을 만들거나 고친다.
2. `config.yaml` 의 `database.model_modules` 에 모듈 경로를 추가한다. (규칙 13)
   Alembic 은 여기 적힌 모듈만 import 하므로, 빠뜨리면 3번 결과가 빈 파일로 나온다.
3. `just makemigrations "설명"` — 모델과 DB 의 차이로 리비전 파일을 만든다.
4. **생성된 `migrations/versions/*.py` 를 반드시 열어서 읽는다.** 자동 생성 결과가 항상
   맞지는 않는다. 의도하지 않은 `drop_table` 이나 `drop_column` 이 들어 있으면 그대로
   실행하지 말고 먼저 사용자에게 알린다.
5. `just migrate upgrade head` — 확인이 끝난 뒤에만 DB 에 적용한다.

되돌릴 때는 `just migrate downgrade -1` 을 쓴다. 지금 어느 리비전인지는
`just migrate current`, 전체 목록은 `just migrate history` 로 본다.

리비전 파일은 **downgrade 로 되돌리기 전에 지우지 않는다.** 먼저 지우면 DB 의
`alembic_version` 테이블만 그 리비전을 가리킨 채 남아서
`Can't locate revision ...` 에러가 나고, 그때는 DB 를 비우는 것 말고 방법이 없다.

### 실행 전에 반드시 사용자 확인을 받는 명령

되돌릴 수 없고 데이터가 사라진다. 임의로 실행하지 않는다. (규칙 3과 같은 맥락)

| 명령 | 무슨 일이 일어나는가 |
| --- | --- |
| `just reset` | 컨테이너를 내리고 볼륨까지 지운다. DB 와 Redis 의 데이터가 전부 사라진다. 실행 뒤에는 `just up`, `just migrate upgrade head` 를 다시 해야 한다. |
| `just migrate downgrade base` | 모든 마이그레이션을 되돌린다. 테이블과 그 안의 데이터가 지워진다. |
| `DELETE FROM alembic_version;` | Alembic 이 "아무것도 적용 안 된 상태"로 인식한다. 테이블 자체는 남아 있어서 다음 `upgrade` 가 "이미 존재함" 에러로 실패할 수 있다. |

### 막혔을 때

`SETUP.md` 의 "6. 안 될 때" 표를 먼저 본다. 자주 나오는 증상과 원인이 정리돼 있다.
표에 없는 증상이면 임의로 추측해서 고치지 말고 사용자에게 묻는다.

## 15. 개발 문서는 `docs/` 아래에 계층별로 쓴다

개발 문서를 만들거나 고칠 때는 루트에 새 마크다운 파일을 흩뿌리지 않는다.
`docs/` 폴더를 만들고 그 아래에 계층 기준으로 파일을 나눈다.

```
docs/
├── data.md        # models/, migrations/, config.yaml 의 model_modules
├── backend.md     # backend/ (api, schemas, services, repositories)
├── frontend.md    # frontend/
└── agent.md       # agent/ (rag, tools)
```

문서를 쓰기 전에 어느 파일에 들어갈 내용인지 먼저 정한다. 한 문서가 여러 계층을
설명하기 시작하면, 그 계층을 고칠 때 어느 문서를 같이 고쳐야 하는지 알 수 없게 된다.

### 어느 문서에 쓰는가

| 내용 | 위치 |
| --- | --- |
| 특정 계층에서 작업하는 순서, 그 계층의 규칙과 판단 기준 | `docs/<계층>.md` |
| 설치·실행 명령, 전체 개발 사이클, 문제 해결 | `SETUP.md` |
| 폴더 구조와 의존 방향 | `STRUCTURE.md` |
| 코드 작성 규칙 | 이 문서(`CLAUDE.md`) |

같은 내용을 두 곳에 적지 않는다. 다른 문서에 이미 있으면 그쪽을 링크한다.
문서가 서로 어긋나면 어느 쪽이 맞는지 알 수 없어진다.

### 지킬 것

- 위 네 파일 외에 다른 문서가 필요해 보이면 **만들기 전에 사용자에게 묻는다.**
  계층이 아닌 기준으로 파일이 늘어나면 분류가 무너진다.
- 코드를 바꿔서 문서 내용이 틀리게 되면 그 문서도 같이 고친다.
- `frontend/README.md` 처럼 폴더 안에 이미 문서가 있으면, 같은 내용을 복사하지 말고
  둘 중 하나를 정본으로 정하고 나머지는 링크만 남긴다.
