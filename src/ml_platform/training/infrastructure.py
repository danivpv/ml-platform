"""
training/infrastructure.py
===========================
CDK construct for the on-demand training Fargate task.

Resources provisioned:
  - Fargate TaskDefinition (0.5 vCPU / 1 GB)
      Container image built from training/runtime/Dockerfile
  - Task IAM role — least-privilege S3 and DynamoDB grants
  - Security group — outbound-only (no inbound rules; this is a task,
    not a service)

Design notes:
  - This is a TaskDefinition, NOT a FargateService. Training runs are
    triggered manually via `aws ecs run-task` (or via CI in a later phase).
    There is no always-on service, no desired count, no auto-scaling.
  - Cross-construct grants (feature bucket, artifacts bucket, online table)
    are applied in component.py after all constructs are instantiated.
  - The MLflow tracking URI is stored in SSM and injected as an ECS Secret
    (not a plaintext env var) so the URI can be updated post-deploy without
    a stack redeployment (see PRD §2.21).
  - Env vars follow the contract defined here; Thread 2 reads them in
    train.py without modification.

Env var contract (available inside the running container):
  FEATURE_BUCKET         — S3 bucket name for offline features + registry
  ONLINE_TABLE           — DynamoDB table name (Feast online store)
  ARTIFACTS_BUCKET       — S3 bucket name for MLflow artifacts
  MLFLOW_TRACKING_URI    — injected from SSM (updated post-deploy)
  AWS_DEFAULT_REGION     — set by ECS agent to the task's region
"""

from pathlib import Path
from typing import Any

from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ssm as ssm,
)
from aws_cdk.aws_ecr_assets import DockerImageAsset
from constructs import Construct

import constants

_ROOT_DIR = str(Path(__file__).resolve().parents[3])


class TrainingConstruct(Construct):
    """
    Provisions the training Fargate task definition.

    Constructor parameters (all keyword-only):
      cluster          — ECS cluster to associate (from ExperimentTracking)
      vpc              — VPC for the task security group
      feature_bucket   — S3 bucket (offline + registry prefixes)
      online_table     — DynamoDB table (Feast online store)
      artifacts_bucket — S3 bucket (MLflow artifact store)
      mlflow_uri_param — SSM parameter holding the MLflow tracking URI

    Exposed properties:
      task_definition  — FargateTaskDefinition (pass to run-task CLI calls)
      task_sg          — security group for the task (component.py wires RDS)
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster: ecs.Cluster,
        vpc: ec2.IVpc,
        feature_bucket_name: str,
        online_table_name: str,
        artifacts_bucket_name: str,
        mlflow_uri_param: ssm.StringParameter,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Security group ─────────────────────────────────────────────────
        # Training task is outbound-only: pulls from S3, writes to DynamoDB,
        # reads from and writes to S3, and calls the MLflow server.
        # Inbound: none (task is not a service).
        self.task_sg = ec2.SecurityGroup(
            self,
            "TrainingSg",
            vpc=vpc,
            description="Training Fargate task - outbound only, no inbound rules",
            allow_all_outbound=True,
        )

        # ── Fargate task definition ────────────────────────────────────────
        training_image = DockerImageAsset(
            self,
            "TrainingImage",
            directory=_ROOT_DIR,
            file="src/ml_platform/training/runtime/Dockerfile",
        )

        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "TrainingTaskDef",
            cpu=constants.TASK_CPU,
            memory_limit_mib=constants.TASK_MEMORY_MB,
        )

        # Grant SSM read so the task can resolve the MLflow URI parameter.
        mlflow_uri_param.grant_read(self.task_definition.task_role)

        self.task_definition.add_container(
            "TrainingContainer",
            image=ecs.ContainerImage.from_docker_image_asset(training_image),
            environment={
                # Static config — CDK tokens resolved at synth time
                "FEATURE_BUCKET": feature_bucket_name,
                "ONLINE_TABLE": online_table_name,
                "ARTIFACTS_BUCKET": artifacts_bucket_name,
            },
            secrets={
                # MLFLOW_TRACKING_URI pulled from SSM at container start.
                # Update the SSM param post-deploy; no redeploy required.
                "MLFLOW_TRACKING_URI": ecs.Secret.from_ssm_parameter(mlflow_uri_param),
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="training"),
        )

        # Store cluster reference for use in component.py run-task examples
        self._cluster = cluster
