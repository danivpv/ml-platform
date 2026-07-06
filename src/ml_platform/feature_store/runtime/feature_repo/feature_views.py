"""
feature_repo/feature_views.py
==============================
Feast FeatureView definitions for the ML Platform.

Data source:
  S3FileSource pointing to s3://${FEATURE_BUCKET}/offline/customer_features/
  Parquet files under this prefix must have these columns:
    entity_id          — String, matches the customer entity join key
    event_timestamp    — Timestamp (UTC), used for point-in-time joins
    age                — Int64
    account_balance    — Float64
    num_transactions   — Int64
    days_since_last_txn — Int64

  The label column (churned: bool) is stored separately at
  s3://${FEATURE_BUCKET}/offline/labels/ — Feast manages features, not labels.

Offline store note (PRD §2.4):
  offline_store.type = "file" + S3FileSource lets Feast read Parquet directly
  from S3 using the file provider with the AWS provider set. The "file" type
  does NOT mean local filesystem; the s3:// path is handled transparently.
"""

from __future__ import annotations

from datetime import timedelta

from feast import FeatureView, Field
from feast.infra.offline_stores.file_source import FileSource
from feast.types import Float64, Int64

from ml_platform.common.schemas import FeastRepoConfig
from ml_platform.feature_store.runtime.feature_repo.entities import customer

# ── Data source ────────────────────────────────────────────────────────────

# FeastRepoConfig reads FEATURE_BUCKET from the environment if present, or falls
# back to a placeholder for local import/testing without failing fast.
_repo_config = FeastRepoConfig()
_feature_bucket = _repo_config.feature_bucket

customer_features_source = FileSource(
    path=f"s3://{_feature_bucket}/offline/customer_features/",
    event_timestamp_column="event_timestamp",
    description=(
        "Customer behavioral features parquet files. "
        f"Resolved bucket: {_feature_bucket}"
    ),
)

# ── Feature views ──────────────────────────────────────────────────────────

customer_features = FeatureView(
    name="customer_features",
    entities=[customer],
    ttl=timedelta(days=365),
    schema=[
        Field(name="age", dtype=Int64),
        Field(name="account_balance", dtype=Float64),
        Field(name="num_transactions", dtype=Int64),
        Field(name="days_since_last_txn", dtype=Int64),
    ],
    source=customer_features_source,
    description="Customer behavioral features for churn prediction (v1 MVP)",
    tags={
        "team": "ml-platform",
        "version": "v1",
        "model": "churn",
    },
    online=True,  # materialized to DynamoDB via `feast materialize`
)

# ── Feature references list (used by train.py and predict.py) ──────────────
# Import this constant instead of spelling out the feature reference strings
# in multiple places (DRY).

CUSTOMER_FEATURE_REFS: list[str] = [
    "customer_features:age",
    "customer_features:account_balance",
    "customer_features:num_transactions",
    "customer_features:days_since_last_txn",
]

FEATURE_COLUMNS: list[str] = [
    "age",
    "account_balance",
    "num_transactions",
    "days_since_last_txn",
]
