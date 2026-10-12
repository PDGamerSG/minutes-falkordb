# Minutes API: FastAPI + agent workers over the Hive Board substrate.
# Build from the repo root:  docker build -f apps/api/Dockerfile -t minutes-api .
#
# * Dependencies are installed with `uv sync --frozen` (uv.lock is authoritative; a stale lock fails the build).
# * The embedding model is downloaded ONCE at build time into /app/hf-cache and verified with a real embedding,
#   so a cold container needs no network to start (HF_HUB_OFFLINE=1) and never mixes embedding models.
# * The runtime stage runs as an unprivileged user and carries no build tooling.

# ---------------------------------------------------------------------------------------- build
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    HF_HOME=/app/hf-cache

WORKDIR /app

# Workspace manifests first so dependency resolution is cached across source edits.
COPY pyproject.toml uv.lock ./
COPY packages/hiveboard/pyproject.toml packages/hiveboard/README.md packages/hiveboard/
COPY packages/ingest/pyproject.toml packages/ingest/
COPY apps/api/pyproject.toml apps/api/
RUN mkdir -p packages/hiveboard/hiveboard packages/hiveboard/bench packages/ingest/ingest cypher \
 && touch packages/hiveboard/hiveboard/__init__.py packages/hiveboard/bench/__init__.py packages/ingest/ingest/__init__.py \
 && uv sync --frozen --no-dev --package minutes-api

# Sources: the substrate, the Cypher files it loads, ingestion, the API and the seed data.
COPY cypher ./cypher
COPY packages ./packages
COPY apps/api ./apps/api
COPY data ./data
COPY docs/bench ./docs/bench
RUN uv sync --frozen --no-dev --package minutes-api

# Bake the embedding model. The Hub cache stores files as symlinks into blobs/, and onnxruntime refuses external
# weights whose resolved path leaves the model directory, so the cache is flattened (symlinks replaced by the real
# files) before the smoke test proves a 768-d vector comes out. The downloading layer is cached separately.
ARG EMBED_MODEL=onnx-community/embeddinggemma-300m-ONNX
RUN /app/.venv/bin/python -c "import sys; from pathlib import Path; from ingest.embed import resolve_model_files; print(resolve_model_files(sys.argv[1], Path('/app/hf-cache/hub')))" "${EMBED_MODEL}"
RUN cp -aL /app/hf-cache /app/hf-cache-flat && rm -rf /app/hf-cache && mv /app/hf-cache-flat /app/hf-cache
RUN /app/.venv/bin/python -c "import sys; from ingest.embed import Embedder; e = Embedder('onnx', sys.argv[1], '/app/hf-cache', None, strict=True); v = e.embed_one('baked model smoke test', 'document'); assert len(v) == 768, len(v); print('embedding model baked:', e.identity, len(v))" "${EMBED_MODEL}"

# ---------------------------------------------------------------------------------------- runtime
FROM python:3.12-slim

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin minutes

ENV PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    HF_HOME=/app/hf-cache \
    HF_HUB_OFFLINE=1 \
    EMBED_MODEL=onnx-community/embeddinggemma-300m-ONNX \
    PORT=8000

WORKDIR /app
COPY --from=build --chown=minutes:minutes /app /app
USER minutes

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
  CMD ["python", "-c", "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4).status == 200 else 1)"]

CMD ["sh", "-c", "exec uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
