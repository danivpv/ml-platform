"""
api/runtime/models.py
======================
Pydantic schemas and SQLModel ORM objects for the Catalog API.
"""

from typing import Optional

from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField

from .base import BaseMetadataModel

# ── SQLModels ──────────────────────────────────────────────────────────────


class Model(BaseMetadataModel, table=True):
    """
    One registered model in the platform catalog.
    Stored in Postgres under the `catalog` schema.
    """

    __tablename__ = "models"
    __table_args__ = {"schema": "catalog"}

    model_name: str = SQLField(unique=True, description="MLflow registered model name")
    feature_view: str = SQLField(description="Feast feature view name")
    feature_refs: str = SQLField(description="Comma-separated Feast feature references")
    label_column: str = SQLField(description="Target column name in labels parquet")
    mlflow_experiment: str = SQLField(description="MLflow experiment name")
    owner: str = SQLField(description="Owning team or engineer")
    cron_schedule: Optional[str] = SQLField(
        default=None,
        description="EventBridge Scheduler cron expression, null if unscheduled",
    )


# ── HTTP Schemas ───────────────────────────────────────────────────────────


class ModelCreateInput(BaseModel):
    """Payload for registering a new model in the catalog."""

    model_name: str = Field(..., description="MLflow registered model name")
    feature_view: str = Field(..., description="Feast feature view name")
    feature_refs: str = Field(
        ..., description="Comma-separated Feast feature references"
    )
    label_column: str = Field(..., description="Target column name in labels parquet")
    mlflow_experiment: str = Field(..., description="MLflow experiment name")
    owner: str = Field(..., description="Owning team or engineer")


class ModelUpdateInput(BaseModel):
    """Payload for updating a model's batch inference schedule."""

    cron_schedule: Optional[str] = Field(
        ...,
        description="EventBridge Scheduler cron expression (e.g. 'rate(1 day)')",
        examples=["rate(1 day)", "cron(0 12 * * ? *)"],
    )


class ModelCreateOutput(Model):
    """Response schema returning the full Model after creation."""

    pass


class ModelReadOutput(Model):
    """Response schema returning the full Model for read operations."""

    pass


class ModelUpdateOutput(Model):
    """Response schema returning the full Model after update."""

    pass


class TaskTriggerOutput(BaseModel):
    """Response schema after triggering an async ECS task."""

    task_arn: str = Field(..., description="The AWS ECS Task ARN for tracking status")
    cluster_arn: str = Field(..., description="The AWS ECS Cluster ARN")


class TaskStatusOutput(BaseModel):
    """Response schema for tracking an ECS task."""

    task_arn: str = Field(..., description="The AWS ECS Task ARN")
    last_status: str = Field(
        ..., description="Current status (e.g. PROVISIONING, RUNNING, STOPPED)"
    )
    desired_status: str = Field(..., description="Target status")
    exit_code: Optional[int] = Field(
        default=None, description="Container exit code (0 is success)"
    )
    stop_reason: Optional[str] = Field(default=None, description="Why the task stopped")
