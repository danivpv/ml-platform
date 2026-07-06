# ==============================================================================
# STAGE 1: THE BUILDER
# ==============================================================================
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_PROGRESS=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Cache Layer 1: Third-Party Dependencies Only
# Uses mount caches and binds for fast, reproducible lockfile installations.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable --no-dev --no-default-groups --group mlflow

# Cache Layer 2: Project Code & Installation
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --no-default-groups --group mlflow

# ==============================================================================
# STAGE 2: FINAL RUNTIME
# ==============================================================================
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual environment intact from the builder (no source files copied to runtime stage!)
COPY --from=builder /app/.venv /app/.venv

# Activate virtual environment by default
ENV PATH="/app/.venv/bin:$PATH"

# ECS agent injects the following env vars at container start via ECS Secrets:
#   DB_USERNAME, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
# and plain env vars:
#   MLFLOW_HOST, MLFLOW_PORT, MLFLOW_ARTIFACT_ROOT
#
# The CMD below constructs the Postgres backend store URI from those vars
# so no plaintext credentials appear in this image or the task definition.
CMD ["sh", "-c", \
     "exec python -m mlflow server \
       --backend-store-uri postgresql://${DB_USERNAME}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME} \
       --artifacts-destination ${MLFLOW_ARTIFACT_ROOT} \
       --host ${MLFLOW_HOST} \
       --port ${MLFLOW_PORT} \
       --allowed-hosts '*' \
       --cors-allowed-origins '*' \
       --workers 1"]
