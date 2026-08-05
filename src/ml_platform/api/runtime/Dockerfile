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
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable --no-dev --no-default-groups --group api

# Cache Layer 2: Project Code & Installation
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --no-default-groups --group api

# ==============================================================================
# STAGE 2: FINAL RUNTIME
# ==============================================================================
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual environment intact from the builder
COPY --from=builder /app/.venv /app/.venv

# Copy Alembic files and entrypoint for DB migrations
COPY --from=builder /app/src/ml_platform/api/runtime/alembic.ini /app/alembic.ini
COPY --from=builder /app/src/ml_platform/api/runtime/alembic /app/alembic
COPY src/ml_platform/api/runtime/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Activate virtual environment by default
ENV PATH="/app/.venv/bin:$PATH"

# Expose API port
EXPOSE 8000

# Run FastAPI catalog app via entrypoint
CMD ["/app/entrypoint.sh"]
