# ==============================================================================
# STAGE 1: THE BUILDER
# ==============================================================================
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_PROGRESS=1
ENV UV_LINK_MODE=copy

WORKDIR /build

# Cache Layer 1: Third-Party Dependencies Only
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable --no-dev --no-default-groups --group inference-training

# Cache Layer 2: Project Code & Installation
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --no-default-groups --group inference-training

# ==============================================================================
# STAGE 2: FINAL RUNTIME
# ==============================================================================
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual environment and project files intact from the builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build /app

# Activate virtual environment by default
ENV PATH="/app/.venv/bin:$PATH"

# ECS agent injects env vars at runtime (see inference/infrastructure.py):
#   FEATURE_BUCKET       — S3 bucket for Feast offline store
#   ONLINE_TABLE         — DynamoDB table for Feast online store
#   ARTIFACTS_BUCKET     — S3 bucket for MLflow artifacts / model registry
#   MLFLOW_TRACKING_URI  — injected from SSM Parameter Store at task start
#   PREDICTIONS_PREFIX   — S3 URI prefix for batch prediction output
CMD ["python", "src/ml_platform/inference/runtime/predict.py"]
