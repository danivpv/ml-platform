"""
tests/unit/test_schemas.py
===========================
Unit tests for runtime Pydantic schemas and the Trainer protocol.

These tests verify:
  1. EntityRow validates correctly and rejects bad input.
  2. PredictionRecord validates correctly and rejects bad input.
  3. SklearnTrainer satisfies the Trainer protocol (isinstance check).
  4. SklearnTrainer.fit() trains without error on synthetic data.
  5. PyTorchTrainer raises NotImplementedError on both methods.
  6. TrainingConfig and InferenceConfig read from environment variables.

No AWS credentials, no Feast, no MLflow server required.
Imports come from src/ml_platform/common/ — which is on sys.path via the
src/ layout recognised by uv/pytest (pyproject.toml build backend = uv_build).

Run:  uv run pytest tests/unit/test_schemas.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from ml_platform.common.schemas import (
    EntityRow,
    FeastRepoConfig,
    InferenceConfig,
    PredictionRecord,
    TrainingConfig,
)
from ml_platform.common.trainer import PyTorchTrainer, SklearnTrainer, Trainer


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


@pytest.fixture()
def synthetic_X() -> pd.DataFrame:
    """Tiny DataFrame matching the customer_features schema."""
    return pd.DataFrame(
        {
            "age": [25, 40, 55, 30, 65],
            "account_balance": [1000.0, 5000.0, 250.0, 15000.0, 500.0],
            "num_transactions": [10, 50, 2, 100, 5],
            "days_since_last_txn": [1, 30, 365, 7, 180],
        }
    )


@pytest.fixture()
def synthetic_y() -> pd.Series:
    """Binary churn labels matching synthetic_X."""
    return pd.Series([0, 0, 1, 0, 1], name="churned")


# ── EntityRow ──────────────────────────────────────────────────────────────


class TestEntityRow:
    def test_valid_construction(self, now_utc: datetime) -> None:
        row = EntityRow(entity_id="cust-001", event_timestamp=now_utc)
        assert row.entity_id == "cust-001"
        assert row.event_timestamp == now_utc

    def test_valid_from_dict(self, now_utc: datetime) -> None:
        row = EntityRow.model_validate(
            {"entity_id": "cust-002", "event_timestamp": now_utc}
        )
        assert row.entity_id == "cust-002"

    def test_valid_iso_string_timestamp(self) -> None:
        """pydantic v2 coerces ISO-8601 strings to datetime."""
        row = EntityRow(
            entity_id="cust-003",
            event_timestamp="2026-01-15T12:00:00Z",  # type: ignore  # testing pydantic coercion
        )
        assert isinstance(row.event_timestamp, datetime)

    def test_missing_entity_id_raises(self, now_utc: datetime) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EntityRow.model_validate({"event_timestamp": now_utc})

    def test_missing_timestamp_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EntityRow.model_validate({"entity_id": "cust-004"})

    def test_invalid_timestamp_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EntityRow(entity_id="cust-005", event_timestamp="not-a-date")  # type: ignore  # testing pydantic rejection


# ── PredictionRecord ───────────────────────────────────────────────────────


class TestPredictionRecord:
    def test_valid_construction(self, now_utc: datetime) -> None:
        rec = PredictionRecord(
            entity_id="cust-001",
            score=0.87,
            model_uri="models:/ml-platform-churn@champion",
            predicted_at=now_utc,
        )
        assert rec.entity_id == "cust-001"
        assert rec.score == pytest.approx(0.87)
        assert rec.model_uri == "models:/ml-platform-churn@champion"

    def test_score_coerced_from_int(self, now_utc: datetime) -> None:
        """pydantic coerces int score to float."""
        rec = PredictionRecord(
            entity_id="cust-002",
            score=1,  # type: ignore[arg-type]
            model_uri="models:/ml-platform-churn@champion",
            predicted_at=now_utc,
        )
        assert isinstance(rec.score, float)
        assert rec.score == 1.0

    def test_missing_score_raises(self, now_utc: datetime) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PredictionRecord.model_validate(
                {
                    "entity_id": "cust-003",
                    "model_uri": "models:/ml-platform-churn@champion",
                    "predicted_at": now_utc,
                }
            )

    def test_json_roundtrip(self, now_utc: datetime) -> None:
        """PredictionRecord.model_dump_json() → model_validate_json() roundtrip."""
        rec = PredictionRecord(
            entity_id="cust-004",
            score=0.42,
            model_uri="models:/ml-platform-churn@champion",
            predicted_at=now_utc,
        )
        json_str = rec.model_dump_json()
        restored = PredictionRecord.model_validate_json(json_str)
        assert restored.entity_id == rec.entity_id
        assert restored.score == pytest.approx(rec.score)


# ── Trainer protocol ───────────────────────────────────────────────────────


class TestTrainerProtocol:
    def test_sklearn_trainer_is_trainer(self) -> None:
        """SklearnTrainer satisfies the Trainer Protocol (runtime_checkable)."""
        trainer = SklearnTrainer()
        assert isinstance(trainer, Trainer)

    def test_pytorch_trainer_is_trainer(self) -> None:
        """PyTorchTrainer satisfies the Trainer Protocol structurally."""
        trainer = PyTorchTrainer()
        assert isinstance(trainer, Trainer)

    def test_sklearn_trainer_fit(
        self, synthetic_X: pd.DataFrame, synthetic_y: pd.Series
    ) -> None:
        """SklearnTrainer.fit() runs without error on synthetic data."""
        trainer = SklearnTrainer()
        trainer.fit(synthetic_X, synthetic_y)
        # Post-fit: the pipeline's final estimator should have classes_.
        assert hasattr(trainer._pipeline.named_steps["clf"], "classes_")

    def test_pytorch_trainer_fit_raises(
        self, synthetic_X: pd.DataFrame, synthetic_y: pd.Series
    ) -> None:
        """PyTorchTrainer.fit() raises NotImplementedError (seam exists, not implemented)."""
        trainer = PyTorchTrainer()
        with pytest.raises(NotImplementedError, match="PyTorchTrainer"):
            trainer.fit(synthetic_X, synthetic_y)

    def test_pytorch_trainer_save_raises(self) -> None:
        """PyTorchTrainer.save() raises NotImplementedError."""
        trainer = PyTorchTrainer()
        with pytest.raises(NotImplementedError, match="PyTorchTrainer"):
            trainer.save(run_id="fake-run-id")


# ── TrainingConfig / InferenceConfig ──────────────────────────────────────


class TestTrainingConfig:
    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FEATURE_BUCKET", "test-feature-bucket")
        monkeypatch.setenv("ONLINE_TABLE", "test-online-table")
        monkeypatch.setenv("ARTIFACTS_BUCKET", "test-artifacts-bucket")
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "file:///tmp/mlruns")

        config = TrainingConfig()  # type: ignore  # pydantic-settings reads from env
        assert config.feature_bucket == "test-feature-bucket"
        assert config.online_table == "test-online-table"
        assert config.artifacts_bucket == "test-artifacts-bucket"
        assert config.mlflow_tracking_uri == "file:///tmp/mlruns"

    def test_missing_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing required env var raises a pydantic ValidationError at startup."""
        from pydantic import ValidationError

        # Remove all required env vars so TrainingConfig construction fails.
        for var in (
            "FEATURE_BUCKET",
            "ONLINE_TABLE",
            "ARTIFACTS_BUCKET",
            "MLFLOW_TRACKING_URI",
        ):
            monkeypatch.delenv(var, raising=False)

        with pytest.raises((ValidationError, Exception)):
            TrainingConfig()  # type: ignore  # pydantic-settings reads from env


class TestInferenceConfig:
    def test_inherits_training_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FEATURE_BUCKET", "test-feature-bucket")
        monkeypatch.setenv("ONLINE_TABLE", "test-online-table")
        monkeypatch.setenv("ARTIFACTS_BUCKET", "test-artifacts-bucket")
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "file:///tmp/mlruns")
        monkeypatch.setenv("PREDICTIONS_PREFIX", "s3://test-bucket/predictions/")

        config = InferenceConfig()  # type: ignore  # pydantic-settings reads from env
        assert config.feature_bucket == "test-feature-bucket"
        assert config.predictions_prefix == "s3://test-bucket/predictions/"

    def test_missing_predictions_prefix_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import ValidationError

        monkeypatch.setenv("FEATURE_BUCKET", "test-feature-bucket")
        monkeypatch.setenv("ONLINE_TABLE", "test-online-table")
        monkeypatch.setenv("ARTIFACTS_BUCKET", "test-artifacts-bucket")
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "file:///tmp/mlruns")
        monkeypatch.delenv("PREDICTIONS_PREFIX", raising=False)

        with pytest.raises((ValidationError, Exception)):
            InferenceConfig()  # type: ignore  # pydantic-settings reads from env


class TestFeastRepoConfig:
    def test_default_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When FEATURE_BUCKET is absent, falls back to placeholder without raising."""
        monkeypatch.delenv("FEATURE_BUCKET", raising=False)
        config = FeastRepoConfig()
        assert config.feature_bucket == "FEATURE_BUCKET_NOT_SET"

    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When FEATURE_BUCKET is present, reads it from environment."""
        monkeypatch.setenv("FEATURE_BUCKET", "my-custom-feature-bucket")
        config = FeastRepoConfig()
        assert config.feature_bucket == "my-custom-feature-bucket"
