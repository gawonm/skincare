# skincare

성분 근거 RAG 와 제품 데이터를 기반으로 스킨케어를 추천하는 서비스.

| 문서 | 내용 |
| --- | --- |
| [SETUP.md](SETUP.md) | 로컬 개발 환경 준비와 매일 쓰는 명령 |
| [STRUCTURE.md](STRUCTURE.md) | 폴더 구조와 import 방향 |
| [CLAUDE.md](CLAUDE.md) | 코드 작성 규칙 |
| [docs/](docs/) | 파트별 담당 범위 문서 |

구성은 FastAPI(백엔드) + React(프론트) + PostgreSQL(ParadeDB: pg_search + pgvector) + Redis 다.

---

# 배포

## 어떻게 도는가

프론트를 빌드해서 **백엔드 이미지 안에 넣고, FastAPI 가 정적 파일까지 서빙**한다.
컨테이너는 `postgres`, `redis`, `backend` 세 개다.

```
브라우저 ── :8000 ── backend (FastAPI)
                       ├── /auth 등 API
                       └── / 그 외 → frontend/dist 정적 파일
                       ├── postgres:5432
                       └── redis:6379
```

프론트를 따로 띄우지 않는 이유는 **오리진을 하나로 유지**하기 위해서다. 세션 쿠키가
`SameSite=lax` 이고 백엔드에 CORS 미들웨어가 없어서, 프론트와 API 의 오리진이 갈리면
로그인이 깨진다. 개발에서 Vite 프록시로 하던 것과 같은 구조다.

## 관련 파일

| 파일 | 역할 |
| --- | --- |
| `Dockerfile` | 1단계에서 프론트 빌드, 2단계에서 백엔드 런타임 + `dist` 복사 |
| `docker-compose.prod.yml` | `backend` 서비스만 정의한 오버레이. 기본 파일과 겹쳐 쓴다 |
| `config.prod.yaml.sample` | 배포용 `config.prod.yaml` 예시. 호스트가 `postgres`, `redis` 다 |
| `.env.example` | Compose 전용 값(DB 계정, 포트) |

`docker-compose.yml` 은 개발·배포 공용이다. `postgres` 와 `redis` 정의를 배포용에 복사해 두면
한쪽만 고쳐서 설정이 조용히 갈라지므로, 오버레이 방식으로 겹쳐 쓴다.

## 첫 배포

### 1. 서버에 필요한 것

- Docker Engine + Docker Compose v2 (`docker compose version`)
- `just` (선택. 없으면 아래 원시 명령을 그대로 친다)

### 2. 저장소 받기

```bash
git clone https://github.com/gawonm/skincare.git
cd skincare
```

### 3. 설정 파일 두 개 만들기

```bash
cp config.prod.yaml.sample config.prod.yaml   # 애플리케이션 설정
cp .env.example .env                          # Compose 전용
```

배포 설정 파일 이름은 `config.yaml` 이 아니라 **`config.prod.yaml`** 이다. 개발용
`config.yaml`(주소가 `localhost`)과 한 머신에 같이 둘 수 있어야 하기 때문이다.
`docker-compose.prod.yml` 이 이 파일을 컨테이너 안의 `/app/config.yaml` 로 마운트한다.

**반드시 바꿀 값**

| 파일 | 항목 | 이유 |
| --- | --- | --- |
| `.env` | `POSTGRES_PASSWORD` | 기본값 `app` 그대로 두지 않는다 |
| `config.prod.yaml` | `database.url` 의 비밀번호 | `.env` 에서 바꾼 값과 **똑같이** 맞춘다 |
| `config.prod.yaml` | `auth.cookie_secure` | HTTPS 뒤에 둔다면 `true`. http 로 그대로 열면 `false` 여야 쿠키가 붙는다 |
| `config.prod.yaml` | `mfds.service_key` | MFDS 수집 스크립트를 서버에서 돌릴 때만 필요 |

두 파일 모두 `.gitignore` 대상이다. **커밋하지 않는다.**

`config.prod.yaml` 의 호스트가 `localhost` 가 아니라 `postgres`, `redis` 인지 확인한다.
컨테이너 안에서 `localhost` 는 자기 자신이라 DB 에 닿지 않는다.

### 4. 기동

```bash
just prod-up
```

`just` 가 없으면:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
```

프론트 빌드(`npm ci`)와 파이썬 의존성 설치가 이미지 안에서 돌기 때문에 **첫 실행은 몇 분** 걸린다.

### 5. 테이블 만들기

```bash
just prod-migrate
```

기동할 때 자동으로 돌리지 않는다. 백엔드를 여러 대로 늘렸을 때 동시에 마이그레이션이 걸려
서로 막히기 때문이다. 배포 직후 한 번만 사람이 실행한다.

### 6. 확인

```bash
curl http://localhost:8000/docs     # API 문서가 뜨면 백엔드 정상
curl -I http://localhost:8000/      # 200 이면 정적 파일 서빙 정상
```

브라우저로 `http://서버주소:8000` 에 접속해 로그인 화면이 뜨는지 본다.

### 7. 데이터 적재 (선택)

성분 근거 RAG 와 제품 가격 데이터는 별도 적재가 필요하다. 절차와 현황은
[docs/data/data.md](docs/data/data.md) 를 따른다.

## 갱신 배포

```bash
git pull
just prod-up          # 이미지 다시 빌드 후 교체
just prod-migrate     # 모델이 바뀐 배포에서만
```

**프론트 코드만 바뀌어도 이미지를 다시 빌드해야 한다.** 정적 파일이 이미지 안에 구워져 있어서
`git pull` 만으로는 화면이 바뀌지 않는다.

## 자주 쓰는 명령

```bash
just prod-up        # 빌드 + 기동, 전부 healthy 될 때까지 대기
just prod-down      # 정지 (데이터 볼륨은 남는다)
just prod-logs      # 로그 따라가기
just prod-migrate   # 컨테이너 안에서 alembic 실행 (기본 upgrade head)
just prod-shell     # 백엔드 컨테이너 셸
```

## 배포 전 확인할 것

- [ ] `.env` 의 `POSTGRES_PASSWORD` 를 기본값에서 바꿨다
- [ ] 배포 호스트에 `config.prod.yaml` 이 있다 — 없는 상태로 기동하면 Docker 가 같은 자리에
      빈 디렉터리를 만들고 앱이 설정을 못 읽어 무한 재시작한다
- [ ] `config.prod.yaml` 의 접속 정보가 `.env` 와 일치한다
- [ ] `config.prod.yaml` 을 커밋하지 않았다 (`git status` 에 안 나와야 한다)
- [ ] HTTPS 를 쓴다면 `auth.cookie_secure: true` 로 바꿨다
- [ ] **5432, 6379 포트가 외부에 열려 있지 않다** — `docker-compose.yml` 이 두 포트를 호스트로
      내보내므로, 공개 서버라면 방화벽에서 막거나 해당 `ports` 항목을 지운다
- [ ] `postgres-data` 볼륨 백업 계획이 있다

## 안 될 때

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| backend 컨테이너가 계속 재시작 | `config.prod.yaml` 의 호스트가 `localhost` | `postgres`, `redis` 로 고친다 |
| backend 컨테이너가 계속 재시작 | 호스트에 `config.prod.yaml` 이 없어 빈 디렉터리가 마운트됨 | 그 자리의 디렉터리를 지우고 `cp config.prod.yaml.sample config.prod.yaml` 후 재기동 |
| `Redis 연결 실패` 로 종료 | Redis 미기동 또는 주소 오류 | `just prod-logs`, `config.prod.yaml` 의 `redis.url` 확인 |
| 화면은 뜨는데 로그인이 안 풀림 | 쿠키가 안 붙음 | http 인데 `cookie_secure: true` 인지 확인 |
| 새로고침하면 404 | 정적 서빙 문제 | `frontend/dist` 가 이미지에 들어갔는지 `just prod-shell` 로 확인 |
| 화면이 예전 그대로 | 이미지 재빌드 누락 | `just prod-up` (`--build` 포함) |
| `relation ... does not exist` | 마이그레이션 미적용 | `just prod-migrate` |
