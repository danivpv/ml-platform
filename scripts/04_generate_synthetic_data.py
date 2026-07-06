"""
scripts/04_generate_synthetic_data.py
====================================
Generate synthetic Parquet data and upload it to the ML Platform feature bucket.

Files written to s3://FEATURE_BUCKET/:
  offline/customer_features/features_synthetic.parquet
      Columns: entity_id, event_timestamp, age, account_balance,
               num_transactions, days_since_last_txn
  offline/labels/labels_synthetic.parquet
      Columns: entity_id, event_timestamp, churned
  offline/entities/train_entities.parquet
      Columns: entity_id, event_timestamp  (label timestamps used by train.py)
  offline/entities/score_entities.parquet
      Columns: entity_id  (no timestamp; predict.py stamps now() at runtime)

Leakage check (PRD sec 2.4):
  Feature timestamps: 7-90 days ago.
  Label timestamps:   0-6 days ago (strictly more recent than features).
  Feast get_historical_features(entity_df=label_ts_rows) finds a valid
  feature row for every entity because feature_ts is always before label_ts.

Usage (PowerShell):
  $env:FEATURE_BUCKET = "<bucket>"
  uv run --no-default-groups --group inference-training `
      python scripts/04_generate_synthetic_data.py

Dry-run (no S3):
  uv run --no-default-groups --group inference-training `
      python scripts/04_generate_synthetic_data.py --dry-run
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RANDOM_SEED = 42
N_CUSTOMERS = 200

FEATURES_PREFIX = "offline/customer_features"
LABELS_PREFIX = "offline/labels"
TRAIN_ENTITIES_KEY = "offline/entities/train_entities.parquet"
SCORE_ENTITIES_KEY = "offline/entities/score_entities.parquet"


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def generate_features(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """
    Customer feature rows with timestamps 7-90 days in the past.

    These are always older than label timestamps (0-6 days ago), guaranteeing
    feature_ts < label_ts for all N_CUSTOMERS rows and preventing data leakage
    in Feast point-in-time joins.
    """
    now = _now_utc()
    feature_days_ago = rng.integers(7, 91, size=n)
    feature_timestamps = [
        now - timedelta(days=int(d), hours=int(rng.integers(0, 24)))
        for d in feature_days_ago
    ]
    return pd.DataFrame(
        {
            "entity_id": [f"cust-{i:04d}" for i in range(n)],
            "event_timestamp": feature_timestamps,
            "age": rng.integers(18, 75, size=n).astype("int64"),
            "account_balance": np.round(rng.uniform(0.0, 50_000.0, size=n), 2),
            "num_transactions": rng.integers(0, 500, size=n).astype("int64"),
            "days_since_last_txn": rng.integers(0, 365, size=n).astype("int64"),
        }
    )


def generate_labels(feature_df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """
    Label rows with timestamps 0-6 days ago (more recent than features).

    Churn probability is a noisy function of balance and inactivity so the
    model has a learnable signal rather than pure random noise.
    """
    now = _now_utc()
    label_days_ago = rng.integers(0, 7, size=len(feature_df))
    label_timestamps = [
        now - timedelta(days=int(d), hours=int(rng.integers(0, 12)))
        for d in label_days_ago
    ]
    balance_norm = feature_df["account_balance"] / 50_000.0
    inactivity_norm = feature_df["days_since_last_txn"] / 365.0
    churn_prob = (0.2 + 0.5 * inactivity_norm - 0.3 * balance_norm).clip(0.05, 0.95)
    churned = rng.random(size=len(feature_df)) < churn_prob.values
    return pd.DataFrame(
        {
            "entity_id": feature_df["entity_id"].values,
            "event_timestamp": label_timestamps,
            "churned": churned.astype(bool),
        }
    )


def generate_score_entities(feature_df: pd.DataFrame) -> pd.DataFrame:
    """Entity IDs only. predict.py stamps event_timestamp = now() at runtime."""
    return pd.DataFrame({"entity_id": feature_df["entity_id"].values})


def _leakage_check(feature_df: pd.DataFrame, labels_df: pd.DataFrame) -> None:
    """
    Verify feature_ts < label_ts for all entities (Feast anti-leakage guarantee).

    If feature_ts >= label_ts, Feast EXCLUDES those feature values and returns
    NaN. That is the correct behaviour. With our synthetic timestamps we expect
    ZERO such rows.
    """
    merged = feature_df[["entity_id", "event_timestamp"]].merge(
        labels_df[["entity_id", "event_timestamp"]],
        on="entity_id",
        suffixes=("_feature", "_label"),
    )
    for col in ("event_timestamp_feature", "event_timestamp_label"):
        if merged[col].dt.tz is None:
            merged[col] = merged[col].dt.tz_localize(timezone.utc)
    n_leaking = (merged["event_timestamp_feature"] >= merged["event_timestamp_label"]).sum()
    if n_leaking > 0:
        logger.warning(
            "LEAKAGE WARN: %d rows have feature_ts >= label_ts (Feast will exclude them).",
            n_leaking,
        )
    else:
        logger.info(
            "LEAKAGE CHECK PASSED: all %d entities satisfy feature_ts < label_ts.",
            len(merged),
        )


def _to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow")
    return buf.getvalue()


def upload_to_s3(df: pd.DataFrame, bucket: str, key: str) -> None:
    import boto3
    body = _to_parquet_bytes(df)
    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=body, ContentType="application/octet-stream"
    )
    logger.info("Uploaded  s3://%s/%s  (%d rows, %d bytes)", bucket, key, len(df), len(body))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and upload synthetic ML Platform feature/label data."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print plan; no S3 writes.")
    parser.add_argument("--n-customers", type=int, default=N_CUSTOMERS)
    args = parser.parse_args()

    bucket = os.environ.get("FEATURE_BUCKET", "")
    if not bucket and not args.dry_run:
        try:
            import boto3
            logger.info("FEATURE_BUCKET env var not set. Auto-discovering from CloudFormation stack MLPlatformStateful...")
            cf = boto3.client("cloudformation")
            res = cf.describe_stacks(StackName="MLPlatformStateful")
            for out in res["Stacks"][0].get("Outputs", []):
                if out["OutputKey"] == "FeatureBucketName":
                    bucket = out["OutputValue"]
                    os.environ["FEATURE_BUCKET"] = bucket
                    logger.info("Auto-discovered FEATURE_BUCKET: %s", bucket)
                    break
        except Exception as e:
            logger.debug("Failed to auto-discover FEATURE_BUCKET: %s", e)

    if not bucket and not args.dry_run:
        logger.error(
            "FEATURE_BUCKET env var not set and could not be auto-discovered from CloudFormation.\n"
            "  PowerShell: $env:FEATURE_BUCKET = '<bucket>'\n"
            "  bash:       export FEATURE_BUCKET=<bucket>"
        )
        sys.exit(1)

    rng = np.random.default_rng(RANDOM_SEED)
    n = args.n_customers

    logger.info("Generating data for %d customers...", n)
    feature_df = generate_features(rng, n)
    labels_df = generate_labels(feature_df, rng)
    train_entities_df = labels_df[["entity_id", "event_timestamp"]].copy()
    score_entities_df = generate_score_entities(feature_df)

    logger.info("Feature shape: %s  columns: %s", feature_df.shape, list(feature_df.columns))
    logger.info("Label shape:   %s  columns: %s", labels_df.shape, list(labels_df.columns))
    logger.info(
        "Feature ts range: %s -> %s",
        feature_df["event_timestamp"].min().strftime("%Y-%m-%d"),
        feature_df["event_timestamp"].max().strftime("%Y-%m-%d"),
    )
    logger.info(
        "Label ts range:   %s -> %s",
        labels_df["event_timestamp"].min().strftime("%Y-%m-%d"),
        labels_df["event_timestamp"].max().strftime("%Y-%m-%d"),
    )
    logger.info("Churn rate: %.1f%%", labels_df["churned"].mean() * 100)
    _leakage_check(feature_df, labels_df)

    if args.dry_run:
        logger.info("DRY RUN -- no S3 uploads.")
        print(f"  {FEATURES_PREFIX}/features_synthetic.parquet  ({n} rows)")
        print(f"  {LABELS_PREFIX}/labels_synthetic.parquet       ({n} rows)")
        print(f"  {TRAIN_ENTITIES_KEY}  ({n} rows)")
        print(f"  {SCORE_ENTITIES_KEY}  ({n} rows)")
        return

    logger.info("Uploading to s3://%s ...", bucket)
    upload_to_s3(feature_df, bucket, f"{FEATURES_PREFIX}/features_synthetic.parquet")
    upload_to_s3(labels_df, bucket, f"{LABELS_PREFIX}/labels_synthetic.parquet")
    upload_to_s3(train_entities_df, bucket, TRAIN_ENTITIES_KEY)
    upload_to_s3(score_entities_df, bucket, SCORE_ENTITIES_KEY)
    logger.info("=== Upload complete ===")
    logger.info("Next: feast apply, then feast materialize-incremental.")


if __name__ == "__main__":
    main()
