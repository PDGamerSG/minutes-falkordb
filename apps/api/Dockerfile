# Minutes API: FastAPI + agent workers over the Hive Board substrate.
# Build from the repo root:  docker build -f apps/api/Dockerfile -t minutes-api .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    HF_HOME=/app/hf-cache \
    API_HOST=0.0.0.0 \
    API_PORT=8000

WORKDIR /app

# Workspace manifests first so dependency resolution is cached across source edits.
COPY pyproject.toml uv.lock* ./
COPY packages/hiveboard/pyproject.toml packages/hiveboard/README.md packages/hiveboard/
COPY packages/ingest/pyproject.toml packages/ingest/
COPY apps/api/pyproject.toml apps/api/
RUN mkdir -p packages/hiveboard/hiveboard packages/hiveboard/bench packages/ingest/ingest cypher \
 && touch packages/hiveboard/hiveboard/__init__.py packages/hiveboard/bench/__init__.py packages/ingest/ingest/__init__.py \
 && (uv sync --frozen --no-dev --package minutes-api || uv sync --no-dev --package minutes-api)

# Sources: the substrate, the Cypher files it loads, ingestion and the API.
COPY cypher ./cypher
COPY packages ./packages
COPY apps/api ./apps/api
COPY data ./data
COPY docs/bench ./docs/bench
RUN uv sync --no-dev --package minutes-api

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD ["uv", "run", "--no-sync", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["uv", "run", "--no-sync", "--package", "minutes-api", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
