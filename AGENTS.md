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
