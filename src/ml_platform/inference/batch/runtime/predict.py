"""
predict.py — ML Platform batch inference entrypoint.

Full flow:
  1. Configure structured JSON logging (CloudWatch Logs Insights compatible).
  2. Load and validate InferenceConfig from ECS-injected env vars.
  3. Set MLflow tracking URI.
  4. Load entity list from S3.
  5. Retrieve historical features from Feast (point-in-time as of now).
  6. Load model via mlflow.pyfunc (alias-based: models:/<name>@champion).
  7. Run model.predict(feature_df).
  8. Validate each output row as PredictionRecord (pydantic).
  9. Write validated predictions to S3 as newline-delimited JSON (NDJSON).

Env var contract (injected by ECS — set in inference/infrastructure.py):
  FEATURE_BUCKET         — S3 bucket for Feast offline store
  ONLINE_TABLE           — DynamoDB table for Feast online store
  ARTIFACTS_BUCKET       — S3 bucket for MLflow artifacts / model registry
  MLFLOW_TRACKING_URI    — MLflow tracking server URI (from SSM)
  PREDICTIONS_PREFIX     — S3 URI prefix for batch output
                           (e.g. s3://<FEATURE_BUCKET>/predictions/)

Model URI format (road-to-prod §2):
  models:/<MODEL_NAME>@champion   ← alias-based, not deprecated stages
  Rollback = reassign the alias; no redeployment needed.

For local smoke testing:
  export MLFLOW_TRACKING_URI=file:///tmp/mlruns
  export PREDICTIONS_PREFIX=s3://<bucket>/predictions/2026-07-05/
  (A @champion alias must exist in the local MLflow registry from a prior
   training run.)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

import mlflow.pyfunc
import pandas as pd
import boto3
from feast import FeatureStore

from pathlib import Path

from ml_platform.logger import configure_logging
from ml_platform.inference.batch.runtime.models import PredictionRecord
from ml_platform.inference.batch.runtime.config import InferenceConfig
import ml_platform.feature_store.runtime.feature_repo as feature_repo_pkg

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MODEL_NAME = "ml-platform-churn"
MODEL_URI = f"models:/{MODEL_NAME}@champion"

# S3 key for the entity list to score (relative to FEATURE_BUCKET).
SCORE_ENTITIES_S3_KEY = "offline/entities/score_entities.parquet"

FEATURE_REFS = [
    "customer_features:age",
    "customer_features:account_balance",
    "customer_features:num_transactions",
    "customer_features:days_since_last_txn",
]

FEATURE_COLUMNS = [
    "age",
    "account_balance",
    "num_transactions",
    "days_since_last_txn",
]


# ── Data loading ───────────────────────────────────────────────────────────


def _load_score_entities(config: InferenceConfig) -> pd.DataFrame:
    """
    Load the entity list to score from S3.

    Stamps each row with the current UTC timestamp as the event_timestamp so
    Feast retrieves features as of "now" (correct for batch scoring: we want
    the most recent available feature values).

    Returns a DataFrame with columns [entity_id, event_timestamp].
    """
    s3_path = f"s3://{config.feature_bucket}/{SCORE_ENTITIES_S3_KEY}"
    logger.info("Loading score entity list", extra={"path": s3_path})

    raw = pd.read_parquet(s3_path)
    logger.info("Score entities loaded", extra={"n_rows": len(raw)})

    now = pd.Timestamp.now(tz=timezone.utc)
    entity_df = pd.DataFrame(
        {
            "entity_id": raw["entity_id"].astype(str),
            "event_timestamp": now,
        }
    )
    return entity_df


def _retrieve_features(entity_df: pd.DataFrame, store: FeatureStore) -> pd.DataFrame:
    """Retrieve historical features for the given entities as of now."""
    logger.info(
        "Retrieving features for inference",
        extra={"n_entities": len(entity_df), "features": FEATURE_REFS},
    )
    job = store.get_historical_features(
        entity_df=entity_df,
        features=FEATURE_REFS,
    )
    feature_df = job.to_df()
    logger.info(
        "Features retrieved",
        extra={"shape": list(feature_df.shape)},
    )
    return feature_df


# ── Inference ──────────────────────────────────────────────────────────────


def _run_inference(
    feature_df: pd.DataFrame,
    config: InferenceConfig,
) -> list[PredictionRecord]:
    """
    Load the champion model and score the feature DataFrame.

    Returns a list of validated PredictionRecord objects.
    Uses mlflow.pyfunc.load_model() — framework-agnostic by construction.
    Inference code never needs to change when the model framework changes.
    """
    logger.info("Loading model", extra={"model_uri": MODEL_URI})
    model = mlflow.pyfunc.load_model(MODEL_URI)
    logger.info("Model loaded", extra={"model_uri": MODEL_URI})

    X = feature_df[FEATURE_COLUMNS].copy()
    raw_scores = model.predict(X)
    predicted_at = datetime.now(tz=timezone.utc)

    # model.predict() returns DataFrame|Series|ndarray|str|bytes|None depending on
    # the framework — coerce through pd.Series for a uniform, type-safe iterable.
    score_series = pd.Series(raw_scores).reset_index(drop=True)

    records: list[PredictionRecord] = [
        PredictionRecord(
            entity_id=str(entity_id),
            score=float(score),
            model_uri=MODEL_URI,
            predicted_at=predicted_at,
        )
        for entity_id, score in zip(
            feature_df["entity_id"].tolist(), score_series.tolist()
        )
    ]

    logger.info(
        "Inference complete",
        extra={"n_predictions": len(records), "model_uri": MODEL_URI},
    )
    return records


# ── Output writing ─────────────────────────────────────────────────────────


def _write_predictions(
    records: list[PredictionRecord],
    config: InferenceConfig,
) -> str:
    """
    Serialize validated PredictionRecord objects to NDJSON and write to S3.

    Output path:
      <PREDICTIONS_PREFIX>predictions_<iso_timestamp>.jsonl

    Returns the full S3 URI of the written file.
    """
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"predictions_{ts}.jsonl"

    # PREDICTIONS_PREFIX is a full s3:// URI (set by InferenceConstruct).
    prefix = config.predictions_prefix.rstrip("/")
    s3_uri = f"{prefix}/{filename}"

    # Parse bucket and key from the s3:// URI.
    # Handles both s3://bucket/prefix/ and s3://bucket/predictions/ formats.
    assert s3_uri.startswith("s3://"), f"Unexpected PREDICTIONS_PREFIX format: {s3_uri}"
    without_scheme = s3_uri[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")

    ndjson_lines = "\n".join(record.model_dump_json() for record in records)
    body = ndjson_lines.encode("utf-8")

    s3 = boto3.client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/x-ndjson")

    logger.info(
        "Predictions written",
        extra={"s3_uri": s3_uri, "n_records": len(records), "bytes": len(body)},
    )
    return s3_uri


# ── Main flow ──────────────────────────────────────────────────────────────


def predict(config: InferenceConfig) -> None:
    """End-to-end batch inference: load → feature retrieval → score → write."""
    mlflow.set_tracking_uri(config.mlflow_tracking_uri)
    logger.info(
        "MLflow configured",
        extra={"tracking_uri": config.mlflow_tracking_uri},
    )

    feature_repo_path = str(Path(feature_repo_pkg.__file__).parent)
    store = FeatureStore(repo_path=feature_repo_path)
    logger.info(
        "FeatureStore initialised",
        extra={"project": store.project, "repo_path": feature_repo_path},
    )

    entity_df = _load_score_entities(config)
    feature_df = _retrieve_features(entity_df, store)

    records = _run_inference(feature_df, config)
    s3_uri = _write_predictions(records, config)

    logger.info("Batch inference complete", extra={"output": s3_uri})


# ── Entrypoint ─────────────────────────────────────────────────────────────


def main() -> None:
    configure_logging()
    logger.info("=== ML Platform — Inference container starting ===")

    try:
        config = InferenceConfig(**{})  # pydantic-settings reads from env
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Configuration validation failed — check ECS env vars",
            extra={"error": str(exc)},
        )
        sys.exit(1)

    logger.info(
        "Configuration loaded",
        extra={
            "feature_bucket": config.feature_bucket,
            "online_table": config.online_table,
            "artifacts_bucket": config.artifacts_bucket,
            "predictions_prefix": config.predictions_prefix,
        },
    )

    try:
        predict(config)
    except Exception as exc:
        logger.exception(
            "Inference failed",
            extra={"error": str(exc)},
        )
        sys.exit(1)

    logger.info("=== ML Platform — Inference container finished ===")


if __name__ == "__main__":
    main()
