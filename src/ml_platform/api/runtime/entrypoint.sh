#!/bin/bash
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting FastAPI server..."
exec uvicorn ml_platform.api.runtime.app:app --host 0.0.0.0 --port 8000
