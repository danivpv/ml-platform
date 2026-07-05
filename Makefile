# ── Profile ───────────────────────────────────────────────────────────────────
# Override on the CLI: make deploy AWS_PROFILE=production
AWS_PROFILE ?= default#oversight-test

# Export so all child processes (cdk, aws cli) inherit the profile
export AWS_PROFILE

.PHONY: lint type-check test deploy deploy-stateful deploy-stateless clean

# ── Quality ───────────────────────────────────────────────────────────────────

lint:
	uv run ruff check --fix
	uv run ruff format

type-check:
# uv run --only-group inference-training ty check src/ml_platform/{inference,training}/runtime --verbose
# uv run --only-group mlflow ty check src/ml_platform/experiment_tracking/runtime
	uv run --only-group infra ty check src/ml_platform/*/infrastructure.py --verbose

test:
	uv run pytest

# ── CDK ───────────────────────────────────────────────────────────────────────

synth:
	uv run cdk synth

deploy-stateful:
	uv run cdk deploy MLPlatformStatefulStack --profile $(AWS_PROFILE)

deploy-stateless:
	uv run cdk deploy MLPlatformStatelessStack --profile $(AWS_PROFILE)

deploy:
	uv run cdk deploy --all --profile $(AWS_PROFILE)

teardown:
	uv run cdk destroy --all --profile $(AWS_PROFILE)

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	rm -rf cdk.out
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true