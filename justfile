# Windows 에서만 PowerShell 을 쓴다. macOS/Linux 는 just 기본값(sh)을 그대로 쓴다.
set windows-shell := ["powershell", "-NoLogo", "-NoProfile", "-Command"]

# 배포용은 기본 파일에 오버레이를 겹쳐서 쓴다. 매번 -f 두 개를 치지 않으려고 변수로 뺀다.
prod_compose := "docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# Alembic 명령 실행. 예: `just migrate upgrade head`, `just migrate downgrade -1`.
migrate +args:
    uv run alembic {{args}}

# 모델 변경분으로 새 리비전 생성. 예: `just makemigrations "create instrument table"`.
makemigrations message:
    uv run alembic revision --autogenerate -m "{{message}}"

# PostgreSQL(pg_search + pgvector) 과 Redis 기동. 둘 다 healthy 될 때까지 기다린다.
up:
    docker compose up -d --wait

# 컨테이너 정지. 데이터 볼륨은 남는다.
down:
    docker compose down

# 컨테이너 정지 + 볼륨 삭제. DB 내용이 사라진다.
reset:
    docker compose down --volumes

logs +args="--tail 100 -f":
    docker compose logs {{args}}

# psql 셸. 계정 정보는 컨테이너 환경 변수에서 가져온다.
psql:
    docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

# redis-cli 셸.
redis:
    docker compose exec redis redis-cli

# FastAPI 개발 서버. 파일이 바뀌면 자동으로 다시 뜬다.
# 예: `just server`, `just server 0.0.0.0 9000`.
server host="127.0.0.1" port="8000":
    uv run uvicorn backend.main:app --reload --host {{host}} --port {{port}}

# ---------- 배포 ----------

# 프론트 빌드가 이미지 안에서 돌아가므로 첫 실행은 몇 분 걸린다.

# 배포용 스택 기동. 이미지를 다시 빌드하고 전부 healthy 될 때까지 기다린다.
prod-up:
    {{prod_compose}} up -d --build --wait

# 배포용 스택 정지. 데이터 볼륨은 남는다.
prod-down:
    {{prod_compose}} down

prod-logs +args="--tail 100 -f":
    {{prod_compose}} logs {{args}}

# 기동할 때 자동으로 돌리지 않는 이유는, 여러 대로 늘렸을 때 동시에 마이그레이션이
# 걸려 서로 막히기 때문이다. 배포 직후 사람이 한 번만 실행한다.

# 배포 컨테이너 안에서 Alembic 실행. 컨테이너가 떠 있어야 한다.
prod-migrate +args="upgrade head":
    {{prod_compose}} exec backend alembic {{args}}

# 배포 컨테이너 셸. 설정이 제대로 들어갔는지 확인할 때 쓴다.
prod-shell:
    {{prod_compose}} exec backend bash
