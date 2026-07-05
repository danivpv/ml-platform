"""
common/schemas.py
==================
Pydantic v2 data contracts shared between training and inference runtimes.

Design notes:
  - EntityRow and PredictionRecord are strict data-shape validators; range/
    sanity checks are intentionally deferred to v2 (see road-to-prod §2).
  - TrainingConfig and InferenceConfig use pydantic-settings so env vars are
    validated at container startup rather than at first use — fail-fast beats
    silent misconfiguration.
  - No FastAPI, no HTTP surface. These schemas are consumed directly by
    train.py and predict.py.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Feature-retrieval contract ─────────────────────────────────────────────


class EntityRow(BaseModel):
    """
    One entity row used to build the entity_df for Feast feature retrieval.

    Extensibility note (road-to-prod §2):
      v2 will add field validators for entity_id format and timestamp bounds.
      The BaseModel base class makes that additive without breaking callers.
    """

    entity_id: str = Field(..., description="Unique customer/entity identifier")
    event_timestamp: datetime = Field(
        ..., description="Point-in-time timestamp for Feast historical feature join"
    )


# ── Prediction output contract ─────────────────────────────────────────────


class PredictionRecord(BaseModel):
    """
    One validated prediction output row, written to S3 as NDJSON.

    Extensibility note (road-to-prod §2):
      v2 will add score bounds validation (0.0 ≤ score ≤ 1.0 for
      probability outputs) and a confidence/calibration field.
    """

    entity_id: str = Field(..., description="Entity this prediction belongs to")
    score: float = Field(..., description="Model output score (raw or probability)")
    model_uri: str = Field(
        ..., description="MLflow model URI used to produce this prediction"
    )
    predicted_at: datetime = Field(
        ..., description="UTC timestamp when the prediction was generated"
    )


# ── Runtime configuration ──────────────────────────────────────────────────


class TrainingConfig(BaseSettings):
    """
    Configuration for the training container, sourced from ECS-injected env vars.

    All fields are required — a missing env var raises a ValidationError at
    startup (fail-fast; no silent defaults that produce wrong behaviour).

    Env var contract (set by TrainingConstruct in training/infrastructure.py):
      FEATURE_BUCKET         — S3 bucket for Feast offline store + registry
      ONLINE_TABLE           — DynamoDB table for Feast online store
      ARTIFACTS_BUCKET       — S3 bucket for MLflow model artifacts
      MLFLOW_TRACKING_URI    — injected from SSM at task start
    """

    model_config = SettingsConfigDict(
        env_ignore_empty=False,
        case_sensitive=False,
    )

    feature_bucket: str
    online_table: str
    artifacts_bucket: str
    mlflow_tracking_uri: str


class InferenceConfig(TrainingConfig):
    """
    Configuration for the inference container, extending TrainingConfig.

    Additional env var (set by InferenceConstruct in inference/infrastructure.py):
      PREDICTIONS_PREFIX — S3 URI prefix for batch prediction output
                           (format: s3://<FEATURE_BUCKET>/predictions/<date>/)
    """

    predictions_prefix: str


class FeastRepoConfig(BaseSettings):
    """
    Configuration for Feast feature repository imports.
    Provides fallback defaults so that importing feature definitions during local
    testing or CI linting does not raise validation errors when AWS container
    environment variables are absent.
    """

    model_config = SettingsConfigDict(
        env_ignore_empty=False,
        case_sensitive=False,
    )

    feature_bucket: str = "FEATURE_BUCKET_NOT_SET"
