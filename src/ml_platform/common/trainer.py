"""
common/trainer.py
==================
Trainer protocol and concrete implementations.

Design rationale (PRD §2.14):
  mlflow.pyfunc is the uniform *inference* interface — no custom Predictor
  class is needed on the serving side. A small Trainer protocol (fit/save)
  captures what genuinely differs between sklearn and PyTorch: the training
  loop and the model-log call. Inference code is framework-agnostic by
  construction because it calls mlflow.pyfunc.load_model().

  PyTorchTrainer is stubbed with NotImplementedError so Thread 3 can assert
  the seam exists and fill it in when GPU training arrives (PRD §2.13,
  road-to-prod §2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


# ── Protocol ───────────────────────────────────────────────────────────────


@runtime_checkable
class Trainer(Protocol):
    """
    Protocol for ML trainers. Concrete implementations must provide:
      fit()  — train the model in-place on (X, y)
      save() — log the trained model to the active MLflow run and return its URI
    """

    def fit(self, X: "pd.DataFrame", y: "pd.Series") -> None:
        """Train the model on feature matrix X and label vector y."""
        ...

    def save(self, run_id: str, artifact_path: str = "model") -> str:
        """
        Log the trained model to the active MLflow run.

        Returns the model URI (e.g. runs:/<run_id>/model) for downstream
        registration. Must be called inside an active mlflow.start_run() context.
        """
        ...


# ── SklearnTrainer ─────────────────────────────────────────────────────────


class SklearnTrainer:
    """
    Concrete Trainer for scikit-learn pipelines.

    Uses a StandardScaler + RandomForestClassifier pipeline as the MVP default.
    The pipeline is intentionally kept simple — the abstraction seam (fit/save)
    means swapping to GradientBoosting or XGBoost later requires only changing
    this class, not train.py.
    """

    def __init__(self) -> None:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        self._pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    RandomForestClassifier(
                        n_estimators=100,
                        random_state=42,
                        n_jobs=-1,
                    ),
                ),
            ]
        )

    def fit(self, X: "pd.DataFrame", y: "pd.Series") -> None:
        """Train the sklearn pipeline on (X, y)."""
        logger.info(
            "Fitting SklearnTrainer",
            extra={"n_samples": len(X), "n_features": X.shape[1]},
        )
        self._pipeline.fit(X, y)
        logger.info("SklearnTrainer fit complete")

    def save(self, run_id: str, artifact_path: str = "model") -> str:
        """
        Log the fitted sklearn pipeline to the active MLflow run.

        run_id is accepted for interface consistency with the protocol but
        mlflow.sklearn.log_model() automatically attaches to the active run.
        """
        import mlflow.sklearn

        model_info = mlflow.sklearn.log_model(
            sk_model=self._pipeline,
            artifact_path=artifact_path,
            input_example=None,  # logged separately via mlflow.log_input()
        )
        logger.info(
            "Model logged to MLflow",
            extra={"model_uri": model_info.model_uri, "run_id": run_id},
        )
        return model_info.model_uri


# ── PyTorchTrainer (stub) ──────────────────────────────────────────────────


class PyTorchTrainer:
    """
    Stub Trainer for PyTorch models.

    Raises NotImplementedError in both methods — the seam exists so Thread 3
    can verify the protocol is in place and fill in the implementation when
    GPU training is needed (PRD §2.14, road-to-prod §2).
    """

    _NOT_IMPLEMENTED_MSG = (
        "PyTorchTrainer is not implemented in v1. "
        "See road-to-prod.md §2 for the implementation roadmap. "
        "Use SklearnTrainer for the current MVP."
    )

    def fit(self, X: "pd.DataFrame", y: "pd.Series") -> None:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)

    def save(self, run_id: str, artifact_path: str = "model") -> str:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)
