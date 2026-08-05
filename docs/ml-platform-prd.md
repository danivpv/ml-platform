# ML Platform MVP — Product Requirements Document

**Timebox:** 16 hours per phase (built solo)
**Goal:** Develop an ML platform for the full model lifecycle applying industry best practices. Understand the reasoning and tradeoffs behind these best practices.
**Guiding constraints:** lowest reasonable cost, AWS-native services only, single AWS account (existing multi-account/SSO setup deferred until CI/CD phase), no monorepo (one component, several logical units).

---

## 1. Scope boundaries

**v1 — single-model pipeline:**
- In v1, we built a single model pipeline with foundational scaffolding that can easily evolve.
- CDK app with feature store, experiment tracking, training, and batch inference constructs
- Feast: offline store (S3) + online store (DynamoDB) + registry
- MLflow: tracking server (Fargate), Postgres backend store, S3 artifacts, model registry
- Scikit-learn training and batch inference
- Minimal CloudWatch monitoring for infra health
- Manual `cdk deploy` via CLI/SSO profile throughout the build

**v2 — Model Catalog & Platform Boundary (current active scope):**
- Integrated a Model Catalog using a FastAPI runtime to serve as the orchestrator.
- Established the platform boundary with an Application Load Balancer (ALB) and NAT Gateway, routing internet traffic securely to isolated private subnets.
- Integrated ORM and Alembic for async SQLAlchemy schema migrations on the existing RDS Postgres database.
- Implemented scalable software design patterns including CQRS (Command Query Responsibility Segregation) and a Domain-Driven exception catalog.
- Decoupled CDK infrastructure using a `PlatformContext` dependency injection pattern.
- Added automated EventBridge schedule management via `aioboto3`.
- Local development environment (`docker-compose` for Postgres/MLflow) to avoid AWS RDS/Fargate running costs during active development.

**Explicitly out of scope for v1/v2:**
- CI/CD pipeline execution (GitHub Actions + CDK Pipelines scaffolded, wired last or in a later session)
- Real-time inference endpoint (Online Serving)
- Model-quality monitoring (drift, accuracy decay)

*See §8 for the authoritative v1–v4 versioning table. That table is the canonical "is X in scope" reference.*

---

## 2. Architecture decision log

Each entry: the user story it satisfies, alternatives considered, and what we're building.
*(Note: Decisions from Phase 1 are archived in the series documentation. The logs below reflect decisions made in the current development phase).*

### 2.1 Platform Boundary & Network Hardening (ALB + NAT Gateway)

**User story:** As the platform owner, I want to securely expose the Model Catalog API without placing containers directly in public subnets, establishing a robust security boundary.

| | |
|---|---|
| Alternatives considered | Defer network hardening to v3 to maintain development speed; keep using public subnets with IP-locked security groups |
| Decision | **Application Load Balancer (ALB) in public subnets, Fargate tasks in Private Subnets with a NAT Gateway** |
| Rationale | Taking the hit on development speed to set up the NAT/ALB *now* prevents massive technical debt and shadow-IT deployments later. An API boundary is completely meaningless if developers can bypass it via public IP addresses. |

### 2.2 API Runtime & CQRS Pattern

**User story:** As a backend developer, I want a structured, scalable way to handle API business logic so that read queries and write commands remain decoupled and testable as the catalog grows.

| | |
|---|---|
| Alternatives considered | Django or Flask; Monolithic Service Class |
| Decision | **FastAPI with CQRS (Command Query Responsibility Segregation)** |
| Rationale | Django is too opinionated and ships with a synchronous ORM that fights our async architecture. Flask lacks native async and Pydantic validation. FastAPI provides native `async/await` (crucial so our EventBridge calls don't block the server). Structurally, using CQRS over a Monolithic Service Class prevents the inevitable 1000-line "God class" with a gigantic `__init__`, keeping commands and queries highly cohesive and testable. |

### 2.3 Database Migrations (Alembic + Async SQLAlchemy)

**User story:** As the platform operator, I want schema changes applied safely and version-controlled, avoiding ad-hoc SQL executions against the RDS database.

| | |
|---|---|
| Alternatives considered | SQLModel `metadata.create_all()`; manual SQL scripts |
| Decision | **Alembic migrations with async SQLAlchemy** |
| Rationale | `create_all()` is unacceptable for production as it doesn't handle schema evolution (like altering columns). Alembic provides a robust, version-controlled migration lifecycle. Using async SQLAlchemy aligns with FastAPI's async event loop, preventing database I/O from blocking the API. |

### 2.4 Observability: Structured Logging & Domain Exceptions

**User story:** As a client of the API, I want predictable error responses, and as an operator, I want to trace failures natively in CloudWatch without manual string parsing.

| | |
|---|---|
| Alternatives considered | Standard `logging.info()` string logs and raising raw `HTTPException(500)` in route handlers |
| Decision | **JSON-structured logging and a centralized Domain-Driven exception catalog** |
| Rationale | Raising generic HTTP exceptions scatters web logic throughout the domain. By combining JSON-structured logging (which CloudWatch parses natively) with strict Domain Exceptions (e.g., `ModelNotFoundError`), we guarantee that every error traces back to a specific domain operation rather than a generic web framework crash. A central exception handler maps these to standard API responses. |

---

## 3. Final project structure

```
ml-platform/
|-- app.py                       # CDK entry point — sandbox stack
|-- constants.py                 # APP_NAME, account/region per stage
|-- cdk.json
|-- cdk.context.json
|-- pyproject.toml               # uv-managed, single lockfile
|-- uv.lock
|-- src/ml_platform/
|   |-- api/                     # Model catalog API (FastAPI, Alembic, CQRS)
|   |   |-- infrastructure.py    # Fargate Task, SG, EventBridge triggers
|   |   `-- runtime/
|   |       |-- Dockerfile
|   |       |-- alembic/         # DB migrations
|   |       |-- commands/        # CQRS commands
|   |       |-- models/          # SQLModel tables
|   |       |-- queries/         # CQRS queries
|   |       |-- repositories/    # Data access layer
|   |       |-- router.py        # /v1/models routes
|   |       `-- services/        # Domain logic, scheduler
|   |-- component.py             # Composes all logical units
|   |-- config.py
|   |-- constants.py
|   |-- exceptions.py            # Domain exceptions catalog
|   |-- experiment_tracking/     # MLflow on Fargate
|   |   |-- infrastructure.py    # RDS Postgres, S3 artifacts, Fargate (no ALB)
|   |   `-- runtime/
|   |       `-- Dockerfile
|   |-- feature_store/           # Feast
|   |   |-- infrastructure.py    # S3 offline store, DynamoDB online store
|   |   `-- runtime/
|   |       `-- feature_repo/    # feature_store.yaml, entity/feature views
|   |-- inference/
|   |   |-- batch/
|   |   |   |-- infrastructure.py # Fargate Task + EventBridge Scheduler
|   |   |   `-- runtime/
|   |   |       |-- Dockerfile
|   |   |       `-- predict.py
|   |   `-- online/              # v2b (BentoML)
|   |-- monitoring/
|   |   `-- infrastructure.py    # CloudWatch dashboard + alarms + SNS
|   `-- training/
|       |-- infrastructure.py    # Fargate task def, IAM role
|       `-- runtime/
|           |-- Dockerfile
|           `-- train.py
|-- tests/
|   └── unit/                    # CDK assertions tests
└── .github/workflows/           # GitHub Actions CI
    └── ci.yml
```

---

## 4. Security concerns

This section documents known security exposure and the hardening required before any production or multi-user deployment. Cross-reference with `road-to-prod.md §8` for the full hardening roadmap.

### 4.1 ECS and EventBridge Scheduler overly broad grants (Catalog API)

**Exposure:** The Catalog API Fargate task has IAM permissions to `ecs:RunTask` and `scheduler:CreateSchedule` on `*` resources. This means a compromised API could schedule arbitrary tasks on arbitrary ECS clusters across the entire AWS account.

**Hardening:** Scope `ecs:RunTask` to the specific Training and Inference task definition ARNs and the specific ECS Cluster ARN. Scope `scheduler:CreateSchedule` to a specific ARN prefix for the nightly inference schedules.

### 4.2 RDS credentials — Secrets Manager (auto-generated)

**Exposure:** RDS password is generated by Secrets Manager and never touches version control. However, any IAM principal with `secretsmanager:GetSecretValue` on the RDS secret can retrieve the plaintext password.

**Mitigation in v2:** The secret's resource policy is not explicitly scoped; only the MLflow and API task roles and the CDK execution role can access it by default IAM policy attachment.

**Hardening:** Enable Secrets Manager rotation, add a resource-based policy on the secret scoping `GetSecretValue` to only the allowed Fargate task role ARNs.

### 4.3 IAM task roles — overly broad S3 grants (Training)

**Exposure:** CDK's `bucket.grant_read_write(role)` grants `s3:*` on `arn:aws:s3:::bucket` and `arn:aws:s3:::bucket/*`. This allows training tasks to list and delete all objects in the feature bucket and artifacts bucket, not just their designated prefixes. (Inference was partially hardened in v2 to only write to `predictions/*`).

**Hardening:** Replace broad `grant_*` calls for training with explicit `aws_iam.PolicyStatement` scoped to the exact required prefixes.

### 4.4 Container images — no CVE scanning

**Exposure:** While `uv.lock` now enforces deterministic dependency pinning, base images and system packages are still unscanned. A vulnerability could exist in the underlying Ubuntu/Debian layers.

**Hardening:** Add Trivy/Grype to CI (`cdk synth` gate) and enable ECR image scanning on push.

### 4.5 Removal Policies — Development vs. Production

**Exposure:** During the development phase (v1 and v2), all stateful resources (S3 buckets, DynamoDB online table, RDS Postgres database) are configured with `RemovalPolicy.DESTROY` (and `auto_delete_objects=True` for S3) to ensure clean CDK teardown/iteration without manual deletion overhead or orphaned resource billing.

**Risk level:** Extremely high if deployed to production. A `cdk destroy` or stack recreation would result in permanent data loss of the feature store (historical/online data) and the experiment/artifact tracking metadata.

**Hardening:** In production staging and prod accounts, stateful resource removal policies **must** be set to `RemovalPolicy.RETAIN` (and `RemovalPolicy.SNAPSHOT` for RDS).
