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
| [GitHub CLI (gh)](https://cli.github.com/) | PR 생성·조회 | `gh --version` |

`just`는 선택이다. 없으면 `justfile` 안의 명령을 직접 쳐도 된다.

Windows 기준 설치:

```powershell
winget install astral-sh.uv
winget install Casey.Just
winget install Docker.DockerDesktop
winget install GitHub.cli
```

## 2. 최초 1회 준비

```bash
# 1) 파이썬 패키지 설치. .venv 가 자동으로 만들어진다.
uv sync --dev

uv tool install rust-just

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

## 5. GitHub CLI (gh) 인증

`gh` 는 PR 을 올리고 확인할 때 쓴다 (CLAUDE.md 규칙 19). 설치만으로는 동작하지 않고,
계정을 한 번 연결해야 한다.

### 최초 1회 로그인

```bash
gh auth login
```

물어보는 것에 이렇게 답한다.

| 질문 | 고를 값 | 이유 |
| --- | --- | --- |
| What account do you want to log into? | GitHub.com | |
| What is your preferred protocol for Git operations? | HTTPS | 이 저장소의 remote 가 HTTPS 다. SSH 를 고르면 remote 와 어긋난다 |
| Authenticate Git with your GitHub credentials? | Yes | `git push` 가 따로 비밀번호를 묻지 않는다 |
| How would you like to authenticate? | Login with a web browser | 토큰을 직접 만들어 붙여 넣는 것보다 실수할 여지가 적다 |

브라우저가 열리면 터미널에 뜬 8자리 코드를 넣고 승인한다. 그다음 확인한다.

```bash
gh auth status
```

`✓ Logged in to github.com account <아이디>` 가 나오면 된 것이다.

### 이 저장소에 쓰기 권한이 있는지 확인한다

로그인이 됐더라도 `gawonm/skincare` 의 collaborator 가 아니면 push 가 거부된다.
PR 을 올리기 전에 먼저 본다.

```bash
gh repo view gawonm/skincare --json viewerPermission
```

`WRITE` 나 `ADMIN` 이면 된다. `READ` 면 저장소 주인에게 collaborator 초대를 받는다.
이 프로젝트는 fork 가 아니라 collaborator 방식으로 작업한다.

### 토큰을 다루는 법

- 토큰은 `gh` 가 OS 키체인에 넣어 관리한다. 직접 꺼내서 파일이나 `.env` 에 적지 않는다.
- 토큰 값을 채팅, 이슈, PR 본문에 붙여 넣지 않는다. 한 번 드러나면 즉시 폐기해야 한다.
- 남의 컴퓨터나 공용 서버에서 로그인했다면 작업이 끝난 뒤 직접 `gh auth logout` 한다.
- 배포 서버에는 `gh` 를 깔지 않는다. 서버는 `git clone` 만 하면 되고(README.md 참고),
  서버에 토큰이 남아 있을수록 서버가 뚫렸을 때 번지는 범위가 커진다.

### 막아 둔 명령

`.claude/settings.json` 에 위험한 명령을 차단해 두었다. Claude Code 로 작업할 때 아래는
실행되지 않고 거부된다.

| 막아 둔 것 | 왜 |
| --- | --- |
| `gh repo delete`, `gh repo archive`, `gh repo edit`, `gh repo rename` | 저장소가 사라지거나 설정이 통째로 바뀐다. 되돌릴 수 없다 |
| `gh pr merge`, `gh pr close` | 머지는 사람이 GitHub 에서 Squash and merge 로 한다 (규칙 19) |
| `gh secret set/delete`, `gh variable set/delete` | 배포 비밀 값이다. 바뀌면 CI 와 배포가 조용히 깨진다 |
| `gh release delete`, `gh release edit` | 배포본 기록이 사라진다 |
| `gh workflow run/enable/disable`, `gh run cancel/delete/rerun` | CI 를 임의로 돌리거나 실행 기록을 지운다 |
| `gh auth logout`, `gh auth token`, `gh auth refresh` | 남의 로그인을 끊거나 토큰을 꺼낸다 |
| `gh ssh-key`, `gh gpg-key` | 계정 전체의 접근 키를 건드린다 |
| `gh api` | 위 제한을 모두 우회할 수 있는 통로라 조회까지 함께 막았다 |
| `git push --force`, `git push -f` | 남의 커밋을 덮어쓴다 (규칙 19) |

조회 명령(`gh pr view/list/diff/status/checks`, `gh repo view`, `gh issue view/list`,
`gh run list/view`, `gh auth status`)은 확인 없이 바로 실행된다.
`gh pr create` 는 막혀 있지 않지만 자동 허용도 아니라서, 실행할 때마다 확인을 묻는다.

이 차단은 **Claude Code 안에서만** 걸린다. 사람이 터미널에서 직접 치는 명령까지 막지는
못한다. 사람에게 위 표는 "하지 않기로 정해 둔 목록" 이다.

## 6. 주의가 필요한 명령

```bash
just reset
```

컨테이너를 내리고 **볼륨까지 지운다. DB 안의 데이터가 전부 사라지고 되돌릴 수 없다.**
실행한 뒤에는 2번의 4~5단계(`just up`, `just migrate upgrade head`)를 다시 해야 한다.

```bash
just migrate downgrade base
```

모든 마이그레이션을 되돌린다. **테이블과 그 안의 데이터가 지워진다.**

## 7. 안 될 때

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `uv sync` 가 pyproject 없다고 함 | `pyproject.toml` 미작성 | 0번 참고 |
| `pre-commit: command not found` | 개발 의존성 미설치 | `uv sync --dev` 후 `uv run pre-commit ...` |
| `just up` 이 멈춘 채 끝나지 않음 | Docker Desktop 미실행 | Docker Desktop 을 먼저 켠다 |
| DB 연결 거부 | 컨테이너 미기동 또는 포트 불일치 | `just up`, `config.yaml` 과 `.env` 의 포트 비교 |
| `makemigrations` 결과가 비어 있음 | `config.yaml` 의 `model_modules` 누락 | 새 모델 모듈 경로를 추가 |
| `Can't locate revision ...` | 리비전 파일을 downgrade 전에 삭제 | 파일을 복원한 뒤 downgrade 부터 |
