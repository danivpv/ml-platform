"""
api/runtime/config.py
======================
Configuration for the catalog API container.
"""

from pydantic import Field

from ml_platform.config import BaseConfig


class ApiConfig(BaseConfig):
    """
    Env vars set by ApiConstruct. Includes database connection details
    and EventBridge scheduler environment context.
    """

    db_username: str = "postgres"
    db_password: str = ""
    db_host: str = "localhost"
    db_port: str = "5432"
    db_name: str = "postgres"

    # ECS / Orchestration Context
    ecs_cluster_name: str = Field(default="")
    ecs_cluster_arn: str = Field(default="")
    training_task_arn: str = Field(default="")
    training_sg_id: str = Field(default="")
    inference_task_arn: str = Field(default="")
    inference_sg_id: str = Field(default="")
    inference_scheduler_role_arn: str = Field(default="")
    private_subnets: str = Field(default="")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    # MLflow Context
    mlflow_tracking_uri: str = Field(default="")

    @property
    def database_url(self) -> str:
        """Returns the asyncpg connection string."""
        return f"postgresql+asyncpg://{self.db_username}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


config = ApiConfig()
