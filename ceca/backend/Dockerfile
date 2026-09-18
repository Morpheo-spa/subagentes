# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer: only reinstalled when the manifest changes.
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

# --- Development image -------------------------------------------------------
# DEVELOPMENT ONLY. It carries the test and lint tool-chain and runs as root,
# because the source tree is bind-mounted from the host and alembic writes new
# migrations back into it. Only docker-compose.dev.yml builds this target, and
# that file has to be passed with -f (audit E-15).
#
# The default ENVIRONMENT/DEBUG below mark the image for what it is: Settings
# refuses to start with DEBUG=true and ENVIRONMENT=production, so pointing this
# image at a production .env stops the container instead of logging every
# statement with its bound parameters.
FROM base AS dev
LABEL com.estampa.target="dev" com.estampa.deployable="false"
ENV ENVIRONMENT=local \
    DEBUG=true
RUN uv pip install --system pytest pytest-asyncio aiosqlite ruff mypy bandit faker
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- Production image --------------------------------------------------------
# No test tooling, no reload, non-root. This is the target docker-compose.yml
# builds for both the API and the worker.
FROM base AS runtime
LABEL com.estampa.target="runtime" com.estampa.deployable="true"
COPY . .

RUN useradd --create-home --uid 10001 estampa \
    && chown -R estampa:estampa /app
USER estampa

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
