"""
training/runtime/config.py
===========================
Configuration for the training container, sourced from ECS-injected env vars.
"""

from ml_platform.config import BaseConfig


class TrainingConfig(BaseConfig):
    """
    Env var contract (set by TrainingConstruct):
      FEATURE_BUCKET         — S3 bucket for Feast offline store
      ONLINE_TABLE           — DynamoDB table for Feast online store
      ARTIFACTS_BUCKET       — S3 bucket for MLflow model artifacts
      MLFLOW_TRACKING_URI    — injected from SSM at task start
      MODEL_NAME             — Target model to train
    """

    feature_bucket: str
    online_table: str
    artifacts_bucket: str
    mlflow_tracking_uri: str
    model_name: str = "ml-platform-churn"
