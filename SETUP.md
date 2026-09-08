# 실행 방법

이 프로젝트를 처음 받아서 돌리기까지의 순서다. 위에서부터 그대로 따라 하면 된다.

## 0. 아직 없는 파일

`.pre-commit-config.yaml` 이 아직 없다. 없는 상태로 `pre-commit install` 을 실행하면 실패한다.
2번의 2단계는 이 파일을 만든 뒤에 하면 된다.

## 1. 미리 깔아 둘 것

| 도구 | 용도 | 확인 명령 |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | 파이썬 버전과 패키지 관리 | `uv --version` |
| Docker Desktop | PostgreSQL, Redis 컨테이너 | `docker --version` |
| [just](https://github.com/casey/just) | 명령 단축 실행 | `just --version` |

`just`는 선택이다. 없으면 `justfile` 안의 명령을 직접 쳐도 된다.

Windows 기준 설치:

```powershell
winget install astral-sh.uv
winget install Casey.Just
winget install Docker.DockerDesktop
```

## 2. 최초 1회 준비

```bash
# 1) 파이썬 패키지 설치. .venv 가 자동으로 만들어진다.
uv sync --dev

# 2) 커밋 전 자동 검사 설치 (git 저장소여야 한다)
uv run pre-commit install

# 3) 설정 파일 두 개 복사
cp config.yaml.sample config.yaml   # 애플리케이션 설정
cp .env.example .env                # Docker Compose 전용

# 4) DB, Redis 컨테이너 기동. 준비될 때까지 기다린다.
just up

# 5) 테이블 생성
just migrate upgrade head
```

`config.yaml`과 `.env`는 **절대 커밋하지 않는다.** `.gitignore`에 들어 있어야 한다.

`config.yaml`의 접속 주소는 `.env`의 값과 맞춰야 한다. 기본값끼리는 이미 맞다.

## 3. 매일 개발할 때

```bash
just up                        # 컨테이너 켜기
uv run uvicorn backend.main:app --reload   # 백엔드 실행 (main.py 작성 후)
just down                      # 다 하면 컨테이너 끄기
```

`just down`은 컨테이너만 멈춘다. DB 내용은 남는다.

## 4. 자주 쓰는 명령

### 패키지

```bash
uv sync --dev                  # 잠금 파일대로 설치 (팀원과 동일한 버전)
uv add httpx                   # 패키지 추가
uv add --dev pytest            # 개발용 패키지 추가
uv remove httpx                # 패키지 제거
```

`uv add` 는 `pyproject.toml`과 잠금 파일을 같이 고친다. `pip install` 은 쓰지 않는다.

### 데이터베이스

```bash
just makemigrations "설명"      # 모델 변경분으로 리비전 생성
just migrate upgrade head      # 최신까지 적용
just migrate downgrade -1      # 한 단계 되돌리기
just migrate current           # 지금 어느 리비전인지 확인
just migrate history           # 리비전 목록
```

`makemigrations` 로 만들어진 파일은 **실행 전에 반드시 열어서 내용을 확인한다.**
자동 생성 결과가 항상 맞지는 않는다.

### 컨테이너

```bash
just up          # 기동
just down        # 정지 (데이터 유지)
just logs        # 로그 보기
just psql        # DB 접속 셸
just redis       # Redis 접속 셸
```

### 검사와 테스트

```bash
uv run pytest                          # 전체 테스트
uv run pytest tests/test_routing.py -q # 특정 파일만
uv run pre-commit run --all-files      # 전체 파일 검사
```

## 5. 주의가 필요한 명령

```bash
just reset
```

컨테이너를 내리고 **볼륨까지 지운다. DB 안의 데이터가 전부 사라지고 되돌릴 수 없다.**
실행한 뒤에는 2번의 4~5단계(`just up`, `just migrate upgrade head`)를 다시 해야 한다.

```bash
just migrate downgrade base
```

모든 마이그레이션을 되돌린다. **테이블과 그 안의 데이터가 지워진다.**

## 6. 안 될 때

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `uv sync` 가 pyproject 없다고 함 | `pyproject.toml` 미작성 | 0번 참고 |
| `pre-commit: command not found` | 개발 의존성 미설치 | `uv sync --dev` 후 `uv run pre-commit ...` |
| `just up` 이 멈춘 채 끝나지 않음 | Docker Desktop 미실행 | Docker Desktop 을 먼저 켠다 |
| DB 연결 거부 | 컨테이너 미기동 또는 포트 불일치 | `just up`, `config.yaml` 과 `.env` 의 포트 비교 |
| `makemigrations` 결과가 비어 있음 | `config.yaml` 의 `model_modules` 누락 | 새 모델 모듈 경로를 추가 |
| `Can't locate revision ...` | 리비전 파일을 downgrade 전에 삭제 | 파일을 복원한 뒤 downgrade 부터 |
