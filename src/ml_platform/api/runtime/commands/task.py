import logging

import boto3
from sqlalchemy.ext.asyncio import AsyncSession

from ml_platform.api.runtime.commands.base import BaseCommand, BaseDBCommand
from ml_platform.api.runtime.config import config
from ml_platform.api.runtime.exceptions import (
    ModelNotFoundError,
    TaskLaunchError,
    UpstreamServiceError,
)
from ml_platform.api.runtime.models.model import TaskStatusOutput, TaskTriggerOutput
from ml_platform.api.runtime.repositories.model import ModelRepository

logger = logging.getLogger(__name__)


class TriggerTrainingCommand(BaseDBCommand):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.repo = ModelRepository(session)
        self.ecs = boto3.client("ecs", region_name=config.aws_region)

    async def _execute(self, model_name: str) -> TaskTriggerOutput:
        model = await self.repo.get_by_name(model_name)
        if not model:
            raise ModelNotFoundError(model_name=model_name)

        subnets = [s.strip() for s in config.private_subnets.split(",") if s.strip()]
        response = self.ecs.run_task(
            cluster=config.ecs_cluster_name,
            taskDefinition=config.training_task_arn,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": [config.training_sg_id],
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "TrainingContainer",
                        "environment": [{"name": "MODEL_NAME", "value": model_name}],
                    }
                ]
            },
        )

        if not response.get("tasks"):
            failures = response.get("failures", [])
            raise TaskLaunchError(
                message=f"Failed to start training task: {failures}",
            )

        task_arn = response["tasks"][0]["taskArn"]
        return TaskTriggerOutput(
            task_arn=task_arn,
            cluster_arn=config.ecs_cluster_name,
        )


class TriggerInferenceCommand(BaseDBCommand):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.repo = ModelRepository(session)
        self.ecs = boto3.client("ecs", region_name=config.aws_region)

    async def _execute(self, model_name: str) -> TaskTriggerOutput:
        model = await self.repo.get_by_name(model_name)
        if not model:
            raise ModelNotFoundError(model_name=model_name)

        subnets = [s.strip() for s in config.private_subnets.split(",") if s.strip()]
        response = self.ecs.run_task(
            cluster=config.ecs_cluster_name,
            taskDefinition=config.inference_task_arn,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": [config.inference_sg_id],
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "InferenceContainer",
                        "environment": [
                            {"name": "MODEL_NAME", "value": model_name},
                            {"name": "FEATURE_REFS", "value": model.feature_refs},
                        ],
                    }
                ]
            },
        )

        if not response.get("tasks"):
            failures = response.get("failures", [])
            raise TaskLaunchError(
                message=f"Failed to start inference task: {failures}",
            )

        task_arn = response["tasks"][0]["taskArn"]
        return TaskTriggerOutput(
            task_arn=task_arn,
            cluster_arn=config.ecs_cluster_name,
        )


class GetTaskStatusCommand(BaseCommand):
    def __init__(self):
        self.ecs = boto3.client("ecs", region_name=config.aws_region)

    async def _execute(self, task_id: str) -> TaskStatusOutput:
        response = self.ecs.describe_tasks(
            cluster=config.ecs_cluster_name, tasks=[task_id]
        )

        if not response.get("tasks"):
            raise UpstreamServiceError(
                message="Task not found or expired from ECS cache (older than 1 hour).",
                status_code=404,
            )

        task = response["tasks"][0]

        # Extract main container status
        containers = task.get("containers", [])
        exit_code = None
        if containers:
            exit_code = containers[0].get("exitCode")

        return TaskStatusOutput(
            task_arn=task["taskArn"],
            last_status=task["lastStatus"],
            desired_status=task["desiredStatus"],
            exit_code=exit_code,
            stop_reason=task.get("stoppedReason"),
        )
