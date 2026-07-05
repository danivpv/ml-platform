"""
train.py — ML Platform training entrypoint.

Full flow:
  1. Configure structured JSON logging (CloudWatch Logs Insights compatible).
  2. Load and validate TrainingConfig from ECS-injected env vars.
  3. Set MLflow tracking URI and experiment.
  4. Load entity list + labels from S3 (or local path for smoke testing).
  5. Retrieve historical features from Feast.
  6. Validate entity rows via EntityRow schema (fail-fast on bad data).
  7. Log input DataFrame lineage to MLflow (not optional — PRD §lineage).
  8. Train model via SklearnTrainer (Trainer protocol seam).
  9. Log params, metrics, and model artifact to MLflow.
  10. Register model in the MLflow registry and assign @champion alias.

Env var contract (injected by ECS — set in training/infrastructure.py):
  FEATURE_BUCKET         — S3 bucket for Feast offline store + registry
  ONLINE_TABLE           — DynamoDB table for Feast online store
  ARTIFACTS_BUCKET       — S3 bucket for MLflow artifacts
  MLFLOW_TRACKING_URI    — MLflow tracking server URI (from SSM)

For local smoke testing:
  export MLFLOW_TRACKING_URI=file:///tmp/mlruns
  export FEATURE_BUCKET=<local-or-s3-bucket>
  export ONLINE_TABLE=<table-name>
  export ARTIFACTS_BUCKET=<bucket-name>
  (Feast feature retrieval requires either a live S3 path or a local parquet
   file — see SETUP.md §11 for the manual smoke test procedure.)
"""

from __future__ import annotations

import logging
import sys
from datetime import timezone

import mlflow
import mlflow.data
import mlflow.data.pandas_dataset
import mlflow.sklearn
import pandas as pd
from feast import FeatureStore
from mlflow import MlflowClient
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

from pathlib import Path

from ml_platform.common.logging_config import configure_logging
from ml_platform.common.schemas import EntityRow, TrainingConfig
from ml_platform.common.trainer import SklearnTrainer
import ml_platform.feature_store.runtime.feature_repo as feature_repo_pkg

# Module-level logger — configure_logging() sets up the JSON formatter.
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MODEL_NAME = "ml-platform-churn"
EXPERIMENT_NAME = "ml-platform-training"
CHAMPION_ALIAS = "champion"
LABEL_COLUMN = "churned"

# S3 key paths within FEATURE_BUCKET (relative to the bucket root).
ENTITIES_S3_KEY = "offline/entities/train_entities.parquet"
LABELS_S3_KEY = "offline/labels/train_labels.parquet"

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


def _load_entities(config: TrainingConfig) -> pd.DataFrame:
    """
    Load entity rows from S3 and validate each row against EntityRow.

    Returns a DataFrame with columns [entity_id, event_timestamp] suitable
    for passing directly to get_historical_features().

    Raises:
      ValidationError — if any row fails EntityRow schema validation.
      Exception       — if the S3 read fails (boto3/s3fs error).
    """
    s3_path = f"s3://{config.feature_bucket}/{ENTITIES_S3_KEY}"
    logger.info("Loading entity list", extra={"path": s3_path})

    raw: pd.DataFrame = pd.read_parquet(s3_path)
    logger.info("Entity rows loaded", extra={"n_rows": len(raw)})

    # Validate each row — pydantic raises ValidationError on first failure.
    # model_validate() is used (not __init__) to support dict-from-row input.
    validated = [EntityRow.model_validate(row) for row in raw.to_dict("records")]

    # Reconstruct a clean DataFrame from validated models for Feast.
    entity_df = pd.DataFrame(
        [
            {"entity_id": r.entity_id, "event_timestamp": r.event_timestamp}
            for r in validated
        ]
    )
    # Feast requires event_timestamp to be timezone-aware.
    if entity_df["event_timestamp"].dt.tz is None:
        entity_df["event_timestamp"] = entity_df["event_timestamp"].dt.tz_localize(
            timezone.utc
        )
    return entity_df


def _load_labels(config: TrainingConfig) -> pd.DataFrame:
    """
    Load label data from S3.

    Returns a DataFrame with columns [entity_id, event_timestamp, churned].
    Feast manages features, not labels — labels are stored separately.
    """
    s3_path = f"s3://{config.feature_bucket}/{LABELS_S3_KEY}"
    logger.info("Loading labels", extra={"path": s3_path})
    labels = pd.read_parquet(s3_path)
    logger.info(
        "Labels loaded", extra={"n_rows": len(labels), "columns": list(labels.columns)}
    )
    return labels


def _retrieve_features(
    entity_df: pd.DataFrame, feature_store: FeatureStore
) -> pd.DataFrame:
    """
    Run a Feast point-in-time join to retrieve historical features.

    The entity_df event_timestamp is used as the point-in-time cutoff so
    features are retrieved as of that timestamp (no label leakage).
    """
    logger.info(
        "Retrieving historical features",
        extra={"n_entities": len(entity_df), "features": FEATURE_REFS},
    )
    job = feature_store.get_historical_features(
        entity_df=entity_df,
        features=FEATURE_REFS,
    )
    feature_df = job.to_df()
    logger.info(
        "Historical features retrieved",
        extra={"shape": list(feature_df.shape), "columns": list(feature_df.columns)},
    )
    return feature_df


# ── Training ───────────────────────────────────────────────────────────────


def _compute_metrics(
    y_true: pd.Series, y_pred: pd.Series, y_prob: pd.Series
) -> dict[str, float]:
    """Compute and return a dict of evaluation metrics for MLflow logging."""
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
    }


def train(config: TrainingConfig) -> None:
    """
    Main training loop.

    1. Load data → 2. Feast feature retrieval → 3. MLflow run
    → 4. Train → 5. Evaluate → 6. Register + alias.
    """
    # ── MLflow setup ──────────────────────────────────────────────────────
    mlflow.set_tracking_uri(config.mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    logger.info(
        "MLflow configured",
        extra={
            "tracking_uri": config.mlflow_tracking_uri,
            "experiment": EXPERIMENT_NAME,
        },
    )

    # ── Feast setup ───────────────────────────────────────────────────────
    # Dynamically locate the feature repo directory from the installed package.
    # The feature_store.yaml resolves FEATURE_BUCKET and ONLINE_TABLE from env.
    feature_repo_path = str(Path(feature_repo_pkg.__file__).parent)
    store = FeatureStore(repo_path=feature_repo_path)
    logger.info(
        "FeatureStore initialised",
        extra={"project": store.project, "repo_path": feature_repo_path},
    )

    # ── Data loading ──────────────────────────────────────────────────────
    entity_df = _load_entities(config)
    labels_df = _load_labels(config)
    feature_df = _retrieve_features(entity_df, store)

    # Merge features with labels on entity_id + event_timestamp.
    # Inner join: entities with no label (or no feature) are dropped.
    merged = feature_df.merge(
        labels_df[["entity_id", "event_timestamp", LABEL_COLUMN]],
        on=["entity_id", "event_timestamp"],
        how="inner",
    )
    logger.info(
        "Data merged",
        extra={
            "n_features": len(feature_df),
            "n_labels": len(labels_df),
            "n_merged": len(merged),
        },
    )

    if merged.empty:
        raise ValueError(
            "Merged training dataset is empty — check that entity IDs and "
            "event timestamps align between the feature parquet and labels parquet."
        )

    X = merged[FEATURE_COLUMNS].copy()
    y = merged[LABEL_COLUMN].copy()

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logger.info(
        "Train/val split",
        extra={"n_train": len(X_train), "n_val": len(X_val)},
    )

    # ── MLflow run ────────────────────────────────────────────────────────
    with mlflow.start_run() as run:
        run_id = run.info.run_id
        logger.info("MLflow run started", extra={"run_id": run_id})

        # ── Data lineage (not optional per PRD) ──────────────────────────
        # Log the full merged training dataset so the run has a pointer to
        # its input data — this is what makes the lineage claim real.
        dataset = mlflow.data.pandas_dataset.from_pandas(
            merged,
            source=f"s3://{config.feature_bucket}/{ENTITIES_S3_KEY}",
            name="customer_features_with_labels",
            targets=LABEL_COLUMN,
        )
        mlflow.log_input(dataset, context="training")
        logger.info("Input dataset logged to MLflow", extra={"run_id": run_id})

        # ── Params ───────────────────────────────────────────────────────
        mlflow.log_params(
            {
                "model_class": "RandomForestClassifier",
                "n_estimators": 100,
                "random_state": 42,
                "n_train": len(X_train),
                "n_val": len(X_val),
                "feature_bucket": config.feature_bucket,
                "features": ",".join(FEATURE_COLUMNS),
                "label_column": LABEL_COLUMN,
            }
        )

        # ── Train ─────────────────────────────────────────────────────────
        trainer = SklearnTrainer()
        trainer.fit(X_train, y_train)

        # ── Evaluate ──────────────────────────────────────────────────────
        y_pred = pd.Series(trainer._pipeline.predict(X_val))
        y_prob = pd.Series(trainer._pipeline.predict_proba(X_val)[:, 1])
        metrics = _compute_metrics(y_val.reset_index(drop=True), y_pred, y_prob)
        mlflow.log_metrics(metrics)
        logger.info("Metrics logged", extra={"run_id": run_id, **metrics})

        # ── Log model ────────────────────────────────────────────────────
        model_uri = trainer.save(run_id=run_id, artifact_path="model")
        logger.info(
            "Model artifact logged",
            extra={"run_id": run_id, "model_uri": model_uri},
        )

        # ── Register + alias ─────────────────────────────────────────────
        # Use alias-based promotion (not deprecated stages — road-to-prod §2).
        # models:/<MODEL_NAME>@champion is the stable URI for inference.
        registered_model = mlflow.register_model(
            model_uri=f"runs:/{run_id}/model",
            name=MODEL_NAME,
            tags={
                "run_id": run_id,
                "f1_score": str(round(metrics["f1_score"], 4)),
                "roc_auc": str(round(metrics["roc_auc"], 4)),
            },
        )
        version = registered_model.version
        logger.info(
            "Model registered",
            extra={
                "model_name": MODEL_NAME,
                "version": version,
                "run_id": run_id,
            },
        )

        client = MlflowClient()
        client.set_registered_model_alias(
            name=MODEL_NAME,
            alias=CHAMPION_ALIAS,
            version=version,
        )
        champion_uri = f"models:/{MODEL_NAME}@{CHAMPION_ALIAS}"
        logger.info(
            "Champion alias assigned",
            extra={
                "model_name": MODEL_NAME,
                "alias": CHAMPION_ALIAS,
                "version": version,
                "champion_uri": champion_uri,
            },
        )

    logger.info(
        "Training complete", extra={"run_id": run_id, "champion_uri": champion_uri}
    )


# ── Entrypoint ─────────────────────────────────────────────────────────────


def main() -> None:
    configure_logging()
    logger.info("=== ML Platform — Training container starting ===")

    try:
        config = TrainingConfig()  # type: ignore  # pydantic-settings reads from env
    except Exception as exc:
        # pydantic-settings raises ValidationError if a required env var is missing.
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
            "mlflow_tracking_uri": config.mlflow_tracking_uri,
        },
    )

    try:
        train(config)
    except Exception as exc:
        logger.exception(
            "Training failed",
            extra={"error": str(exc)},
        )
        sys.exit(1)

    logger.info("=== ML Platform — Training container finished ===")


if __name__ == "__main__":
    main()
