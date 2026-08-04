"""
inference/batch/runtime/config.py
==================================
Configuration for the batch inference container, sourced from ECS-injected env vars.
"""

from ml_platform.training.runtime.config import TrainingConfig


class InferenceConfig(TrainingConfig):
    """
    Extends TrainingConfig.
    Additional env var (set by InferenceConstruct):
      PREDICTIONS_PREFIX — S3 URI prefix for batch prediction output
    """

    predictions_prefix: str
    database_url: str
