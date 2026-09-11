# 프론트 빌드 결과를 백엔드 이미지 안에 넣어 한 컨테이너에서 서빙한다.
# 개발에서 Vite 프록시로 단일 오리진을 만들던 것과 같은 조건을 배포에서도 유지하려는 것이다.
# 오리진이 갈리면 세션 쿠키(SameSite=lax)가 붙지 않아 로그인이 깨진다.

# ---------- 1단계: 프론트 빌드 ----------
FROM node:22-alpine AS frontend-builder

WORKDIR /build

# package.json 과 lock 만 먼저 복사한다. 소스만 바뀌었을 때 npm ci 캐시를 재사용하기 위해서다.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------- 2단계: 백엔드 런타임 ----------
FROM python:3.13-slim AS runtime

# uv 는 태그를 고정한다. 최신으로 두면 빌드 시점마다 동작이 달라질 수 있다.
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /bin/uv

# .pyc 를 쓰지 않고 로그를 버퍼링하지 않는다. 컨테이너 로그가 바로 보이게 하려는 것이다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # 가상환경을 이미지 안 고정 경로에 만든다. 아래 PATH 와 짝이다.
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 의존성 파일만 먼저 복사해 레이어를 나눈다. 코드가 바뀌어도 uv sync 를 다시 하지 않는다.
COPY pyproject.toml uv.lock ./
# --frozen: lock 파일을 그대로 쓴다. 빌드 중에 의존성이 조용히 올라가는 것을 막는다.
# --no-dev: pytest, ruff 같은 개발 의존성은 이미지에 넣지 않는다.
RUN uv sync --frozen --no-dev --no-install-project

# 백엔드와 RAG가 사용하는 데이터 처리 모듈만 포함한다. 원본 데이터는 제외한다.
COPY data/__init__.py ./data/__init__.py
COPY data/scripts/ ./data/scripts/
COPY core/ ./core/
COPY models/ ./models/
COPY agent/ ./agent/
COPY backend/ ./backend/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# 1단계에서 만든 정적 파일. backend/main.py 가 이 경로를 찾는다.
COPY --from=frontend-builder /build/dist ./frontend/dist

# config.yaml 은 이미지에 굽지 않는다. 비밀값이 들어 있어 이미지가 유출되면 같이 새기 때문이다.
# 실행할 때 볼륨으로 마운트한다 (docker-compose.prod.yml 참고).

EXPOSE 8000

# --reload 는 쓰지 않는다. 배포에서는 파일이 바뀌지 않고, 감시 프로세스가 메모리만 더 쓴다.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
