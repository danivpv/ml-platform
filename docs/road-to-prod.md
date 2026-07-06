# Path to Production

Companion to `ml-platform-prd.md`. This is the v2+ roadmap in four dimensions: what changes when more than one person works on this, what a model needs to be trustworthy in production, what changes to support real-time consumption via a Streamlit UI, and the security hardening that comes with exposing anything beyond a solo sandbox.

None of this is in scope for the current 16-hour build — it's what "done" looks like next.

---

## 1. Multi-person collaboration

| Area | v1/v2 (now) | Production |
|---|---|---|
| AWS access | Single IP-locked security group, one SSO profile | IAM Identity Center permission sets per persona (data scientist / ML engineer / platform admin), least-privilege per role, no shared credentials |
| Environments | One sandbox account | dev → staging → prod accounts (your existing multi-account setup), promotion gates between them |
| Deploys | Manual `cdk deploy` from CLI | CI/CD wired for real: PRs run lint/test/synth (GitHub Actions), merges trigger CDK Pipelines deploy — this is exactly the deferred item from the PRD, now becoming necessary rather than optional |
| Infra changes | Direct edits | Branch protection, required PR review, `CODEOWNERS` splitting infra vs. runtime paths so the right person reviews the right diff |
| Feature changes | Direct `feast apply` | Feature definitions reviewed via `feast plan` output in PR before apply; feature ownership tags so people know who to ask about a given feature view |
| Experiment tracking | Single user, no auth | MLflow behind proper authn (MLflow's built-in basic auth, or an ALB + Cognito/OIDC proxy for SSO-style login); runs tagged with the user who created them |
| Secrets/config | Env vars, single account | Secrets Manager with scoped access per role, no plaintext credentials anywhere, rotation enabled |
| Discoverability | You remember what exists | A lightweight index (even just a README table) of registered models and feature views, so a second person doesn't duplicate a feature that already exists |
| Notifications | None | Pipeline results and model registration events posted to Slack/email, so promotions are visible to the team, not just the person who did it |

---

## 2. Features needed for models in production

| Area | What's needed | Notes |
|---|---|---|
| Promotion mechanism | **Model aliases**, not stages | MLflow deprecated stage-based promotion (Staging/Production/Archived) in favor of aliases (`@champion`, `@challenger`) — aliases are reassignable without a fixed state machine and support multiple aliases per version, which is what A/B testing needs. Serving code targets `models:/<name>@champion` and never hardcodes a version number. |
| Approval gate | Manual or automated sign-off before an alias moves | A promotion should require either a human approval step in the pipeline, or an automated gate: don't reassign `@champion` unless the new version beats the current one on a validation set. |
| Rollback | Reassign the alias to the previous version | This is the actual advantage of aliases over stages — rollback is a one-line alias reassignment, not a redeploy. |
| Canary / shadow deployment | Run challenger alongside champion before full promotion | Applies once real-time serving exists — score both, compare, then promote. For batch, this can be as simple as scoring with both models and diffing outputs before cutting over. |
| Input validation | Schema + range checks before scoring | Already have pydantic schemas from the runtime thread — extend with sanity bounds (not just types) so a malformed or adversarial input doesn't silently produce nonsense predictions. |
| Reproducibility | Pin the training data snapshot, not just the code | Anchor `get_historical_features()` to a fixed timestamp/version, and log the dependency lockfile hash on the MLflow run — "reproduce this model" should mean re-running against the exact same data and code, not just the same code. |
| Monitoring | Drift + performance tracking (see Q2 above) | Not optional in production — this is what tells you a model has silently gone stale. |
| Retraining trigger | Scheduled, or drift-triggered | Start with a schedule (simplest); graduate to triggering retraining automatically when the monitoring job crosses a drift threshold. |
| SLAs & alerting | Latency/availability targets once real-time exists | Alert on breach, not just on outright failure. |
| Audit trail | Who promoted what, when | CloudTrail + MLflow tags tied to IAM identity — a governance requirement the moment more than one person can promote a model. |

---

## 3. Real-time consumption via a Streamlit UI

This is the point where several deferred items become necessary together, not independently:

1. **Online feature store returns to scope.** This is exactly the trigger event that finally justifies DynamoDB (see Q1 above) — a user-facing UI making one-off prediction requests needs `get_online_features()`, not a batch join.
2. **A real serving layer, not a batch job.** Given low/bursty traffic from a simple internal tool, **Lambda + Function URL** is still the leaner default over an always-on Fargate service — unless you're already running FastAPI as a persistent service for other reasons, in which case a small Fargate task with FastAPI + Uvicorn is reasonable too. Either way:
   - **FastAPI** now earns its place — `/predict`, `/health`, `/model-info` routes, request/response validation via the pydantic schemas you already have, and CORS enabled for the Streamlit origin.
   - Model kept warm rather than reloaded per request (Lambda provisioned concurrency, or load-once-at-startup if on Fargate) — reloading a pyfunc model on every cold invocation will dominate your latency budget otherwise.
3. **Streamlit hosting itself.** Needs a home — a small Fargate service or App Runner container running the Streamlit app, calling the FastAPI backend over HTTPS.
4. **AuthN between Streamlit and the API.** Even something simple (API key, or a Cognito-issued token) — don't leave the prediction endpoint open just because it's "internal."
5. **Request logging.** Structured logs (request ID, features used, prediction, latency) to CloudWatch so a Streamlit-triggered prediction is traceable end-to-end — this also feeds directly into the monitoring job from Q2.

---

## 4. Cybersecurity hardening

| Area | v1/v2 (now) | Hardened |
|---|---|---|
| Network | Default VPC, public subnet, single-IP security group | Private subnets for all compute, NAT Gateway or VPC endpoints (S3, DynamoDB, ECR, Secrets Manager) to avoid public egress, ALB with ACM-issued TLS fronting any real-time API instead of a raw public IP |
| IAM | Task roles scoped per-workload | Add permission boundaries, eliminate any remaining wildcard resource ARNs, confirm zero static credentials anywhere (SSO/IAM roles only) |
| Secrets | Env vars for config | RDS credentials and MLflow auth in Secrets Manager with rotation enabled — not plaintext env vars |
| Encryption at rest | Default AWS encryption | SSE-KMS with a customer-managed key on S3 buckets holding training data/artifacts; confirm RDS and DynamoDB encryption use a CMK if data sensitivity warrants it |
| Encryption in transit | Default TLS on AWS-managed services | Enforce SSL on RDS connections, put MLflow behind HTTPS (ALB + ACM) rather than plain HTTP on a public IP |
| Public-facing protection | None (no public endpoint exists yet) | WAF on the ALB/API fronting the Streamlit backend once it exists — blocks common web attacks and rate-limits abuse |
| Account-level | — | CloudTrail enabled account-wide, VPC Flow Logs, GuardDuty for threat detection, AWS Config rules to catch drift (e.g., a bucket accidentally made public) |
| Application-level | pydantic validates shape | Add size limits and timeouts at the API layer to prevent resource-exhaustion abuse; rate-limit the prediction endpoint specifically to slow down model-extraction-via-mass-querying attempts |
| Dependency hygiene | uv lockfile | Scan container images for CVEs before deploy (Trivy/Grype in CI), `pip-audit`/equivalent on the lockfile |
| Data governance | — | Classify any PII in training data, set S3 lifecycle/retention policies, restrict training-data-location access to only the roles that need it |
| Data Persistence / Removal | `DESTROY` (clean teardown) | `RETAIN` (S3/DynamoDB) and `SNAPSHOT` (RDS) enforced to prevent accidental data loss |

---

## Sequencing note

Realistically, these four dimensions aren't independent — the Streamlit work (§3) pulls in the online store, FastAPI, and a public-facing endpoint, which immediately triggers most of the network/API items in the hardening list (§4). Multi-person collaboration (§1) and production-model governance (§2) can be built incrementally without waiting on §3, but §3 and §4 arrive together in practice: the day you expose a real-time endpoint to a UI is the day the security hardening stops being optional.

---

## 5. Multi-model architecture

The v1 MVP is deliberately coupled to a single churn model: `entities.py`, `feature_views.py`, `train.py`, and `predict.py` all hardcode the entity type, feature references, label column, and S3 data paths. This is correct for proving the pipeline works. What follows is the design for when a second model needs to be added.

### The problem: accidental coupling at every layer

| Layer | What is hardcoded in v1 | Why it breaks for model N |
|---|---|---|
| `entities.py` | `customer` entity with `entity_id` join key | A fraud model might need `(txn_id, merchant_id)`, a pricing model `(product_id, region_id)` |
| `feature_views.py` | `customer_features` with 4 fixed columns | Different models need different features and source schemas |
| `train.py` | `MODEL_NAME`, `FEATURE_COLUMNS`, `LABEL_COLUMN` as module constants | Every new model requires a container fork or a new entrypoint |
| `predict.py` | Same constants, `@champion` alias hardcoded to one model name | Scoring the wrong model silently |
| `Trainer` protocol | `SklearnTrainer` is the only concrete implementation | No dispatcher to select the right implementation at runtime |

### Layer 1: Model catalog in PostgreSQL (the source of truth)

This is metadata about what models exist and how to train them — not artifact storage (MLflow owns artifacts).

```sql
-- Entity types decoupled from models
CREATE TABLE entity_types (
    name        TEXT PRIMARY KEY,         -- "customer", "transaction", "product"
    join_keys   TEXT[] NOT NULL,          -- ["entity_id"] or ["txn_id", "merchant_id"]
    description TEXT
);

-- Registered models
CREATE TABLE models (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL UNIQUE,   -- "churn", "fraud", "ltv"
    label_column  TEXT NOT NULL,          -- "churned", "is_fraud", "ltv_usd"
    entity_type   TEXT REFERENCES entity_types(name),
    trainer_class TEXT NOT NULL,          -- "SklearnTrainer", "XGBoostTrainer"
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Feature references per model (replaces FEATURE_REFS constant)
CREATE TABLE model_features (
    model_id     UUID REFERENCES models(id),
    feature_ref  TEXT NOT NULL,           -- "customer_features:age"
    PRIMARY KEY (model_id, feature_ref)
);

-- S3 data source locations per model (replaces hardcoded S3 key constants)
CREATE TABLE model_data_sources (
    model_id         UUID REFERENCES models(id) PRIMARY KEY,
    entities_s3_key  TEXT NOT NULL,
    labels_s3_key    TEXT NOT NULL
);
```

### Layer 2: Abstract `BaseMLModel` (replaces the `Trainer` Protocol)

The current `Trainer` protocol captures `fit/save`, but doesn't force a model to declare what Feast features it needs, what label column it expects, or what entity type it operates on. An abstract base class makes the contract explicit:

```python
# common/base_model.py
from abc import ABC, abstractmethod

class BaseMLModel(ABC):
    """All models must declare their own feature and data contract."""

    @property
    @abstractmethod
    def feature_refs(self) -> list[str]:
        """Feast feature references. e.g. ['customer_features:age']"""
        ...

    @property
    @abstractmethod
    def feature_columns(self) -> list[str]:
        """Column names after Feast retrieval. Must align with feature_refs."""
        ...

    @property
    @abstractmethod
    def label_column(self) -> str:
        """Label column name in the labels parquet."""
        ...

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None: ...

    @abstractmethod
    def save(self, run_id: str, artifact_path: str = "model") -> str: ...
```

Each model is then fully self-describing:

```python
class ChurnModel(BaseMLModel):
    feature_refs    = ["customer_features:age", "customer_features:account_balance", ...]
    feature_columns = ["age", "account_balance", ...]
    label_column    = "churned"
    ...

class FraudModel(BaseMLModel):
    feature_refs    = ["txn_features:amount", "txn_features:merchant_risk_score", ...]
    feature_columns = ["amount", "merchant_risk_score", ...]
    label_column    = "is_fraud"
    ...
```

### Layer 3: Generic `TrainingDispatcher` (replaces hardcoded train.py constants)

A single dispatcher accepts any `BaseMLModel` and runs the generic training loop:

```python
# common/dispatcher.py
class TrainingDispatcher:
    def run(self, model: BaseMLModel, model_name: str, config: TrainingConfig) -> str:
        # Everything generic: Feast retrieval, MLflow tracking, alias assignment
        # Everything model-specific: delegated to model.feature_refs / model.label_column
        store = FeatureStore(...)
        entity_df = self._load_entities(model_name, config)  # DB → S3 key
        feature_df = store.get_historical_features(entity_df, model.feature_refs)
        X, y = feature_df[model.feature_columns], labels[model.label_column]
        with mlflow.start_run():
            model.fit(X, y)
            model.save(...)
            # register, alias — identical for all models
```

`train.py` and `predict.py` become thin launchers: read `MODEL_NAME` from the environment, look it up in a registry dict or the catalog DB, instantiate the right `BaseMLModel` subclass, pass it to the dispatcher.

### Layer 4: REST API for model management

Once `BaseMLModel` + dispatcher exist, a thin FastAPI layer makes model management operational:

```
POST /models                  → Register a new model in the catalog
GET  /models                  → List all models + latest MLflow metrics per model
GET  /models/{name}           → Get model config, version history, current champion URI
POST /models/{name}/train     → Trigger ECS training task for this model
POST /models/{name}/predict   → Trigger ECS batch inference task
POST /models/{name}/promote   → Reassign @champion alias (with optional gate: new > current on validation set)
DELETE /models/{name}/champion → Roll back by pointing @champion at the previous version
```

This replaces the current paradigm of "one container = one model". The same training and inference images serve any model — the dispatcher selects the right `BaseMLModel` subclass based on `MODEL_NAME` injected by the EventBridge Scheduler payload or ECS task override.

### Sequencing for multi-model support

```
v1 (now)    One model, hardcoded config — proves the Feast + MLflow + ECS pipeline end-to-end.

v2          Abstract BaseMLModel + dispatcher: train.py becomes model-agnostic.
            ChurnModel is the first concrete class. No DB yet — model class is selected
            by MODEL_NAME env var mapped to a Python dict. Adding a new model = a new
            Python class + a dict entry, not a CDK change.

v3          PostgreSQL model catalog + CRUD API: decouples model registration from code
            deploys. Adding a new model = a DB insert + a new BaseMLModel subclass.
            The API makes model management visible to teammates (§1 discoverability).

v4          Dynamic Feast feature repo: entity types and feature views are registered
            via the catalog DB and applied to Feast programmatically via `feast apply`,
            eliminating the static feature_repo/ Python files entirely. This is where
            onboarding a new model truly requires zero infrastructure code changes.
```

---

## 6. Long-Term Data Platform & Feature Engineering ETL Integration

In v1 and v2, feature engineering is handled via lightweight domain ETL scripts (such as `04_generate_synthetic_data.py`) that compute domain transformations and output clean Parquet files to the offline S3 bucket (`s3://bucket/offline/features/...`). Feast acts strictly as the retrieval and serving boundary.

As the platform scales beyond initial use cases, this feature preparation layer evolves into a formal Data Platform integration:
- **Dedicated Transformation Engines:** Replacing single-node scripts with scalable ETL pipelines (e.g., AWS Glue, EMR Spark, or dbt on Snowflake/Redshift) that run on automated cron schedules before Feast registration.
- **Data Quality & Schema Contracts:** Automated data validation (e.g., Great Expectations or AWS Glue DataBrew) enforcing nullity, type checks, and distribution bounds at the S3 Parquet boundary before allowing Feast to ingest or materialize.
- **Cross-Team Feature Governance:** Decoupling raw data preparation from ML training jobs entirely, enabling data engineering teams to own offline S3 feature generation while ML engineers consume those features seamlessly via Feast point-in-time joins.
