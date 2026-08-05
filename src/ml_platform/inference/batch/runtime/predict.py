"""
predict.py — ML Platform batch inference entrypoint.

Full flow:
  1. Load InferenceConfig from env vars.
  2. Set MLflow tracking URI.
  3. Query Postgres (or local SQLite) Model Catalog for the specific model's feature_refs.
  4. Load entity list from S3.
  5. Fetch features from Feast using the resolved feature_refs.
  6. Load model via mlflow.pyfunc (alias-based: models:/<name>@champion).
  7. Run model.predict(feature_df).
  8. Write validated predictions to S3 as NDJSON.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import mlflow.pyfunc
import pandas as pd
from feast import FeatureStore
import ml_platform.feature_store.runtime.feature_repo as feature_repo_pkg
from ml_platform.inference.batch.runtime.config import InferenceConfig
from ml_platform.inference.batch.runtime.models import PredictionRecord
from ml_platform.logger import configure_logging

logger = logging.getLogger(__name__)



def _load_score_entities(config: InferenceConfig) -> pd.DataFrame:
    s3_key = f"offline/entities/{config.model_name}_score_entities.parquet"
    s3_path = f"s3://{config.feature_bucket}/{s3_key}"
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


def _retrieve_features(
    entity_df: pd.DataFrame, store: FeatureStore, config: InferenceConfig
) -> pd.DataFrame:
    # feature_refs is a comma-separated string from the config
    feature_list = [f.strip() for f in config.feature_refs.split(",") if f.strip()]
    logger.info(
        "Retrieving features for inference",
        extra={"n_entities": len(entity_df), "features": feature_list},
    )
    job = store.get_historical_features(
        entity_df=entity_df,
        features=feature_list,
    )
    feature_df = job.to_df()
    logger.info("Features retrieved", extra={"shape": list(feature_df.shape)})
    return feature_df


def _run_inference(
    feature_df: pd.DataFrame,
    config: InferenceConfig,
) -> list[PredictionRecord]:
    model_uri = f"models:/{config.model_name}@champion"
    logger.info("Loading model", extra={"model_uri": model_uri})
    loaded_model = mlflow.pyfunc.load_model(model_uri)
    logger.info("Model loaded", extra={"model_uri": model_uri})

    # The loaded sklearn pipeline natively handles dropping unused columns if it's a ColumnTransformer
    # For safety, we just pass the raw feature DF (minus entity/timestamp columns) to the pipeline
    drop_cols = ["entity_id", "event_timestamp"]
    X = feature_df.drop(columns=[c for c in drop_cols if c in feature_df.columns])

    raw_scores = loaded_model.predict(X)
    predicted_at = datetime.now(tz=timezone.utc)
    score_series = pd.Series(raw_scores).reset_index(drop=True)

    records: list[PredictionRecord] = [
        PredictionRecord(
            entity_id=str(entity_id),
            score=float(score),
            model_uri=model_uri,
            predicted_at=predicted_at,
        )
        for entity_id, score in zip(
            feature_df["entity_id"].tolist(), score_series.tolist()
        )
    ]

    logger.info(
        "Inference complete",
        extra={"n_predictions": len(records), "model_uri": model_uri},
    )
    return records


def _write_predictions(
    records: list[PredictionRecord],
    config: InferenceConfig,
) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{config.model_name}_predictions_{ts}.jsonl"

    prefix = config.predictions_prefix.rstrip("/")
    s3_uri = f"{prefix}/{filename}"

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


def predict(config: InferenceConfig) -> None:
    mlflow.set_tracking_uri(config.mlflow_tracking_uri)
    logger.info("MLflow configured", extra={"tracking_uri": config.mlflow_tracking_uri})

    feature_repo_path = str(Path(feature_repo_pkg.__file__).parent)
    store = FeatureStore(repo_path=feature_repo_path)
    logger.info("FeatureStore initialised", extra={"repo_path": feature_repo_path})

    entity_df = _load_score_entities(config)
    feature_df = _retrieve_features(entity_df, store, config)

    records = _run_inference(feature_df, config)
    s3_uri = _write_predictions(records, config)

    logger.info("Batch inference complete", extra={"output": s3_uri})


def main() -> None:
    configure_logging()
    logger.info("=== ML Platform — Multi-Model Inference container starting ===")

    try:
        config = InferenceConfig(**{})
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Configuration validation failed — check ECS env vars",
            extra={"error": str(exc)},
        )
        sys.exit(1)

    logger.info("Configuration loaded", extra={"model_name": config.model_name})

    try:
        predict(config)
    except Exception as exc:
        logger.exception("Inference failed", extra={"error": str(exc)})
        sys.exit(1)

    logger.info("=== ML Platform — Inference container finished ===")


if __name__ == "__main__":
    main()
