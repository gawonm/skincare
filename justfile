# Windows 에서만 PowerShell 을 쓴다. macOS/Linux 는 just 기본값(sh)을 그대로 쓴다.
set windows-shell := ["powershell", "-NoLogo", "-NoProfile", "-Command"]

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
