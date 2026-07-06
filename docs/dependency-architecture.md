# ML Platform Dependency & Architecture Guide

This document details how dependency management is architected in `ml-platform` using `uv`. To maintain production-grade container security, minimize Docker image sizes, and prevent dependency conflicts between cloud infrastructure tools and data science libraries, dependencies are strictly segregated into isolated groups.

---

## 1. Dependency Group Architecture

In a full-stack ML Platform, mixing Infrastructure-as-Code (CDK) dependencies with runtime ML libraries (Feast, Scikit-Learn, PyTorch/TensorFlow, Pandas) inside a single flat virtual environment causes severe version resolution failures and bloated production containers.

### Group Mapping & File Tree
We partition the codebase into three primary operational domains:

```text
src/ml_platform/
├── common/                     ➔ [inference-training] (Shared Pydantic schemas & ML training loop)
├── component.py                ➔ [infra] (Core AWS CDK platform constructs)
├── experiment_tracking/        
│   ├── infrastructure.py       ➔ [infra] (RDS Postgres, ECS Fargate cluster, Secrets Manager)
│   └── runtime/                ➔ [mlflow] (MLflow tracking server Dockerfile)
├── feature_store/              
│   ├── infrastructure.py       ➔ [infra] (S3 offline store, DynamoDB online store)
│   └── runtime/feature_repo/   ➔ [inference-training] (Feast entities, feature views, yaml config)
├── inference/                  
│   ├── infrastructure.py       ➔ [infra] (Batch inference ECS task definitions & schedule)
│   └── runtime/                ➔ [inference-training] (predict.py batch inference runtime & Dockerfile)
├── monitoring/                 
│   └── infrastructure.py       ➔ [infra] (CloudWatch dashboards, alarms, EventBridge rules)
└── training/                   
    ├── infrastructure.py       ➔ [infra] (Training pipeline ECS task definitions)
    └── runtime/                ➔ [inference-training] (train.py model training job & Dockerfile)
```

### Why `conflicts` is Defined in `pyproject.toml`
In `pyproject.toml`, you will notice the following rule:
```toml
[tool.uv]
default-groups = ["dev"]
conflicts = [[{ group = "infra" }, { group = "inference-training" }]]
```
**Why do `infra` and `inference-training` conflict?**
AWS CDK (`aws-cdk-lib>=2.260.0`) hard-requires `typeguard==2.13.3` for JSII runtime type checking. However, modern Feast (`feast[aws]>=0.40.0`) requires `typeguard>=4.0.0`. Because these two requirements are mathematically unsatisfiable in a single Python environment, `uv` explicitly isolates them so that CDK deployment scripts and ML runtime containers never collide.

---

## 2. Essential `uv` Commands & Workflow Tips

### Tip 1: Understanding `default-groups = ["dev"]`
By setting `default-groups` to **`["dev"]`** (and removing `infra` from default), we achieve a clean, frictionless developer workflow.
* **Why?** The `dev` group contains universal developer tooling (`pytest`, `ruff`, `ty`) that is completely compatible with **all** domains (`infra`, `inference-training`, and `mlflow`).
* When you run `uv run --group infra <cmd>` or `uv run --group inference-training <cmd>`, `uv` automatically layers that specific domain group on top of `dev` without needing verbose `--no-default-groups` override flags.

### Tip 2: Simplified Group-Isolated Execution
When running test suites, linting, or CDK operations, simply specify the target domain group:

```bash
# Run unit tests for ML training, feature store, and schemas
uv run --group inference-training pytest tests/unit/test_schemas.py

# Run unit tests for AWS infrastructure constructs (using bash brace expansion)
uv run --group infra pytest --ignore=cdk.out tests/unit/{test_experiment_tracking,test_feature_store,test_inference,test_monitoring,test_training}.py

# Execute CDK synthesis or deployment
uv run --group infra cdk deploy --all --require-approval never
```

### Tip 3: Type Checking (`ty`) & Global Fallbacks
If type checking fails with errors like `Cannot resolve imported module`, it is because the type checker was executed without the required dependency group active in the virtual environment.

**Beware of Global Fallbacks:** If `ty` is installed globally on your machine (e.g., in `~/.local/bin/ty` or via `pipx`), running bare `ty check` in bash will fall back to that global binary if `dev` is not installed in your active virtualenv. A global binary lacks visibility into `uv`'s group-isolated site-packages and will fail to resolve imports.
* **Fix:** If you have an unwanted global installation, remove it (`rm ~/.local/bin/ty*` or `pipx uninstall ty`).
* **Best Practice:** Always invoke `ty` via `uv run` with the explicit group required for that module:

```bash
# Check infrastructure modules
uv run --group infra ty check src/ml_platform/*/infrastructure.py src/ml_platform/component.py app.py constants.py --verbose

# Check runtime ML modules (training, inference, feature store, common)
uv run --group inference-training ty check src/ml_platform/{inference,training,feature_store}/runtime src/ml_platform/common --verbose

# Check MLflow server runtime
uv run --group mlflow ty check src/ml_platform/experiment_tracking/runtime --verbose
```
*(Note: All of these commands are pre-configured in the `make type-check` and `make test` targets in the project `Makefile`).*

---

## 3. Multi-Stage Build Pattern in Runtime Dockerfiles

To guarantee small production container images and prevent infrastructure libraries from leaking into runtime environments, all three production services (`training/runtime`, `inference/runtime`, and `experiment_tracking/runtime`) implement a standardized multi-stage `uv` build pattern:

```dockerfile
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
    uv sync --frozen --no-install-project --no-editable --no-dev --no-default-groups --group <TARGET_GROUP>

# Cache Layer 2: Project Code & Installation
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --no-default-groups --group <TARGET_GROUP>

# ==============================================================================
# STAGE 2: FINAL RUNTIME
# ==============================================================================
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
```

### Why This Design is Crucial:
1. **`--no-default-groups --group <TARGET_GROUP>`**: By passing `--group mlflow` or `--group inference-training`, `uv` installs strictly what that container requires. AWS CDK (`aws-cdk-lib`), Node/JSII binaries, `pytest`, `ruff`, and `ty` are completely excluded from the production container image.
2. **Eliminates `pip install` bugs**: Installing packages via `uv sync` from our lockfile ensures that required transitive dependencies like `setuptools` (which provides `pkg_resources`) are reliably bundled into `/app/.venv`, preventing runtime crashes like `ModuleNotFoundError: No module named 'pkg_resources'`.
3. **`--frozen`**: Ensures container builds fail immediately if `pyproject.toml` and `uv.lock` are out of sync, guaranteeing reproducible deployments.
5. **Layered Build Caching**: Installing third-party dependencies before copying application source code ensures that modifying `.py` scripts does not invalidate the multi-megabyte library layer (Pandas, Scikit-Learn, Feast, PyArrow, MLflow), resulting in sub-second Docker rebuilds during iteration.
6. **Virtualenv Shebang Path Alignment**: Using `WORKDIR /app` in both Stage 1 (builder) and Stage 2 (runtime) ensures that when `uv` installs console scripts (like `mlflow` or `pytest`), their shebang line (`#!/app/.venv/bin/python`) matches the exact path where `.venv` is placed in the final container image, completely eliminating `ENOENT` (`exec: <cmd>: not found`) path relocation errors.
