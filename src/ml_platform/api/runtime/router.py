"""
api/runtime/router.py
======================
FastAPI routes for the Catalog API.
Delegates all business logic to commands and queries.
"""

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from ml_platform.api.runtime.commands.model import (
    CreateModelCommand,
    UpdateModelScheduleCommand,
)
from ml_platform.api.runtime.commands.task import (
    GetTaskStatusCommand,
    TriggerInferenceCommand,
    TriggerTrainingCommand,
)
from ml_platform.api.runtime.db import get_session
from ml_platform.api.runtime.models.model import (
    ModelCreateInput,
    ModelCreateOutput,
    ModelReadOutput,
    ModelUpdateInput,
    ModelUpdateOutput,
    TaskStatusOutput,
    TaskTriggerOutput,
)
from ml_platform.api.runtime.queries.model import GetModelQuery, ListModelsQuery

router = APIRouter()


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Lightweight health check endpoint for ALB target group."""
    return {"status": "ok"}


@router.post(
    "/v1/models", response_model=ModelCreateOutput, status_code=status.HTTP_201_CREATED
)
async def register_model(
    model_in: ModelCreateInput, session: AsyncSession = Depends(get_session)
):
    """Register a new model in the catalog."""
    command = CreateModelCommand(session)
    return await command.execute(model_in)


@router.get("/v1/models", response_model=List[ModelReadOutput])
async def list_models(session: AsyncSession = Depends(get_session)):
    """List all registered models."""
    query = ListModelsQuery(session)
    return await query.execute()


@router.get("/v1/models/{model_name}", response_model=ModelReadOutput)
async def get_model(model_name: str, session: AsyncSession = Depends(get_session)):
    """Get a registered model by name."""
    query = GetModelQuery(session)
    return await query.execute(model_name)


@router.post("/v1/models/{model_name}/schedule", response_model=ModelUpdateOutput)
async def update_schedule(
    model_name: str,
    schedule_in: ModelUpdateInput,
    session: AsyncSession = Depends(get_session),
):
    """
    Update a model's batch inference schedule.
    If cron_schedule is null, deletes the schedule in EventBridge.
    """
    command = UpdateModelScheduleCommand(session)
    return await command.execute(model_name, schedule_in)


@router.post(
    "/v1/models/{model_name}/train",
    response_model=TaskTriggerOutput,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_training(
    model_name: str, session: AsyncSession = Depends(get_session)
):
    """Trigger an asynchronous training task on ECS."""
    command = TriggerTrainingCommand(session)
    return await command.execute(model_name)


@router.post(
    "/v1/models/{model_name}/predict",
    response_model=TaskTriggerOutput,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_inference(
    model_name: str, session: AsyncSession = Depends(get_session)
):
    """Trigger an asynchronous batch inference task on ECS."""
    command = TriggerInferenceCommand(session)
    return await command.execute(model_name)


@router.get("/v1/tasks/{task_id:path}", response_model=TaskStatusOutput)
async def get_task_status(task_id: str):
    """Get real-time ECS task status for a running/stopped container."""
    command = GetTaskStatusCommand()
    return await command.execute(task_id)
