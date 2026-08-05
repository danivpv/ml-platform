"""
api/runtime/scheduler.py
=========================
Async EventBridge Scheduler interactions using aioboto3.
"""

import json
import logging

import aioboto3

from ml_platform.api.runtime.config import config

logger = logging.getLogger(__name__)


async def upsert_schedule(model_name: str, cron_expression: str, feature_refs: str) -> None:
    """
    Creates or updates an EventBridge Scheduler rule for a model's batch inference.
    """
    rule_name = f"ml-platform-inference-{model_name}"

    # We pass the MODEL_NAME env var as an ECS container override so the
    # train.py / predict.py generic containers know which model to run.
    ecs_parameters = {
        "TaskDefinitionArn": config.inference_task_arn,
        "TaskCount": 1,
        "LaunchType": "FARGATE",
        "NetworkConfiguration": {
            "awsvpcConfiguration": {
                "Subnets": [s for s in config.private_subnets.split(",") if s],
                "SecurityGroups": [config.inference_sg_id],
                "AssignPublicIp": "DISABLED",
            }
        },
    }

    # Override the MODEL_NAME env var in the container.
    # The container name in the inference task is "InferenceContainer".
    container_overrides = [
        {
            "Name": "InferenceContainer",
            "Environment": [
                {"Name": "MODEL_NAME", "Value": model_name},
                {"Name": "FEATURE_REFS", "Value": feature_refs},
            ],
        }
    ]

    session = aioboto3.Session(region_name=config.aws_region)
    async with session.client("scheduler") as client:
        try:
            # Check if schedule exists
            await client.get_schedule(Name=rule_name)
            exists = True
        except client.exceptions.ResourceNotFoundException:
            exists = False

        kwargs = {
            "Name": rule_name,
            "ScheduleExpression": cron_expression,
            "ScheduleExpressionTimezone": "UTC",
            "State": "ENABLED",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "Target": {
                "Arn": config.ecs_cluster_arn,
                "RoleArn": config.inference_scheduler_role_arn,
                "EcsParameters": ecs_parameters,
                # Pass the container overrides in the ECS input JSON
                "Input": json.dumps({"containerOverrides": container_overrides}),
            },
        }

        if exists:
            logger.info(f"Updating schedule {rule_name}")
            await client.update_schedule(**kwargs)
        else:
            logger.info(f"Creating schedule {rule_name}")
            await client.create_schedule(**kwargs)


async def delete_schedule(model_name: str) -> None:
    """
    Deletes the EventBridge Scheduler rule for a model if it exists.
    """
    rule_name = f"ml-platform-inference-{model_name}"
    session = aioboto3.Session(region_name=config.aws_region)

    async with session.client("scheduler") as client:
        try:
            await client.delete_schedule(Name=rule_name)
            logger.info(f"Deleted schedule {rule_name}")
        except client.exceptions.ResourceNotFoundException:
            logger.info(f"Schedule {rule_name} does not exist, nothing to delete")
