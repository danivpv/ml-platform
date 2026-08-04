"""
experiment_tracking/constants.py
================================
Constants specific to the MLflow tracking server and RDS instance.
"""

MLFLOW_IMAGE_PORT = 5000
MLFLOW_FARGATE_CPU = 512
MLFLOW_FARGATE_MEMORY_MB = 2048

RDS_DB_NAME = "mlflowdb"
RDS_PORT = 5432
