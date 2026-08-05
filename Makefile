# ── Profile ───────────────────────────────────────────────────────────────────
# Override on the CLI: make deploy AWS_PROFILE=production
AWS_PROFILE ?= default

# Export so all child processes (cdk, aws cli) inherit the profile
export AWS_PROFILE

.PHONY: lint type-check test docker-build docker-test docker-compose-up \
		docker-compose-down deploy deploy-stateful deploy-stateless clean

# ── Quality ───────────────────────────────────────────────────────────────────

lint:
	uv run ruff check --fix
	uv run ruff format

type-check:
	uv run --group infra ty check src/ml_platform/*/infrastructure.py src/ml_platform/component.py app.py src/ml_platform/*.py --verbose
	uv run --group inference-training ty check src/ml_platform/{inference/batch,training,feature_store}/runtime --verbose
	uv run --group mlflow ty check src/ml_platform/experiment_tracking/runtime --verbose
	uv run --group api ty check src/ml_platform/api/runtime --verbose

test:
	uv run --group infra pytest --ignore=cdk.out tests/unit/{test_experiment_tracking,test_feature_store,test_inference,test_monitoring,test_training}.py
	uv run --group inference-training pytest --ignore=cdk.out tests/unit/test_schemas.py

# ── Docker ────────────────────────────────────────────────────────────────────

docker-build:
	docker build -f src/ml_platform/experiment_tracking/runtime/Dockerfile -t ml-platform/mlflow:latest .
	docker build -f src/ml_platform/training/runtime/Dockerfile -t ml-platform/training:latest .
	docker build -f src/ml_platform/inference/batch/runtime/Dockerfile -t ml-platform/inference:latest .
	docker build -f src/ml_platform/api/runtime/Dockerfile -t ml-platform/api:latest .

docker-test:
	docker build -t api-test -f src/ml_platform/api/runtime/Dockerfile .

docker-compose-up:
	docker-compose up -d

docker-compose-down:
	docker-compose down -v

# ── CDK ───────────────────────────────────────────────────────────────────────

synth:
	uv run --group infra cdk synth --profile $(AWS_PROFILE)

deploy-stateful:
	uv run --group infra cdk deploy MLPlatformStateful --require-approval never --profile $(AWS_PROFILE)

deploy-stateless:
	uv run --group infra cdk deploy MLPlatformStateless --require-approval never --profile $(AWS_PROFILE)

deploy:
	uv run --group infra cdk deploy --all --require-approval never --profile $(AWS_PROFILE)

destroy:
	uv run --group infra cdk destroy --all --profile $(AWS_PROFILE)

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	rm -rf cdk.out
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true