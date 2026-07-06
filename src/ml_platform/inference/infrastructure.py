"""
inference/infrastructure.py
============================
CDK construct for the batch inference Fargate task and its EventBridge Scheduler.

Resources provisioned:
  - Fargate TaskDefinition (0.5 vCPU / 1 GB)
      Container image built from inference/runtime/Dockerfile
  - IAM scheduler role — allows EventBridge Scheduler to call ECS RunTask
  - Security group — outbound-only (no inbound rules)
  - EventBridge Scheduler rule — nightly cron (configurable via constants.py)

Design notes:
  - TaskDefinition only, NOT a FargateService. The scheduler invokes
    `RunTask` on the task definition on a schedule; no always-on service.
  - CfnSchedule (L1) is used because there is no stable L2 for EventBridge
    Scheduler in aws-cdk-lib yet (see PRD §2.22).
  - The scheduler role must be allowed to `ecs:RunTask` on the task definition
    AND `iam:PassRole` for both the task role and execution role. This is the
    minimum permission set required by ECS.
  - Cross-construct IAM grants (feature bucket, artifacts bucket, online table)
    are applied in component.py after all constructs are instantiated.
  - PRD §6.6: inference tasks are assigned a public IP (required for ECR image
    pull in the default VPC without VPC endpoints). No inbound SG rules exist;
    the public IP is outbound-only.

Env var contract (available inside the running container):
  FEATURE_BUCKET         — S3 bucket name (offline features + registry)
  ONLINE_TABLE           — DynamoDB table name (Feast online store)
  ARTIFACTS_BUCKET       — S3 bucket name (MLflow artifacts / model registry)
  MLFLOW_TRACKING_URI    — injected from SSM
  PREDICTIONS_PREFIX     — S3 prefix where batch outputs are written
                           (format: s3://<FEATURE_BUCKET>/predictions/)
  AWS_DEFAULT_REGION     — set by ECS agent
"""

import json
from pathlib import Path
from typing import Any

from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_scheduler as scheduler,
    aws_ssm as ssm,
)
from aws_cdk.aws_ecr_assets import DockerImageAsset
from constructs import Construct

import constants

_ROOT_DIR = str(Path(__file__).resolve().parents[3])


class InferenceConstruct(Construct):
    """
    Provisions the batch inference Fargate task definition and the
    EventBridge Scheduler rule that triggers it nightly.

    Constructor parameters (all keyword-only):
      cluster              — ECS cluster to target for RunTask
      vpc                  — VPC for security group
      feature_bucket_name  — S3 bucket name (feature store)
      online_table_name    — DynamoDB table name (online store)
      artifacts_bucket_name — S3 bucket name (MLflow artifacts)
      mlflow_uri_param     — SSM parameter for MLflow tracking URI
      public_subnet_ids    — public subnet IDs for the RunTask network config

    Exposed properties:
      task_definition — FargateTaskDefinition
      task_role       — IAM role (component.py applies grants)
      task_sg         — security group
      schedule        — CfnSchedule (L1 EventBridge Scheduler rule)
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
        # Outbound-only: inference reads from S3/DynamoDB, writes to S3,
        # and calls the MLflow server. No inbound rules.
        self.task_sg = ec2.SecurityGroup(
            self,
            "InferenceSg",
            vpc=vpc,
            description="Inference Fargate task - outbound only, no inbound rules",
            allow_all_outbound=True,
        )

        # ── Fargate task definition ────────────────────────────────────────
        inference_image = DockerImageAsset(
            self,
            "InferenceImage",
            directory=_ROOT_DIR,
            file="src/ml_platform/inference/runtime/Dockerfile",
        )

        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "InferenceTaskDef",
            cpu=constants.TASK_CPU,
            memory_limit_mib=constants.TASK_MEMORY_MB,
        )

        # Grant SSM read so the task can resolve the MLflow URI parameter.
        mlflow_uri_param.grant_read(self.task_definition.task_role)

        self.task_definition.add_container(
            "InferenceContainer",
            image=ecs.ContainerImage.from_docker_image_asset(inference_image),
            environment={
                "FEATURE_BUCKET": feature_bucket_name,
                "ONLINE_TABLE": online_table_name,
                "ARTIFACTS_BUCKET": artifacts_bucket_name,
                # predictions/ prefix within the feature bucket
                "PREDICTIONS_PREFIX": f"s3://{feature_bucket_name}/predictions/",
            },
            secrets={
                "MLFLOW_TRACKING_URI": ecs.Secret.from_ssm_parameter(mlflow_uri_param),
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="inference"),
        )

        # ── EventBridge Scheduler ──────────────────────────────────────────
        # The scheduler role must be able to:
        #   1. ecs:RunTask on this task definition
        #   2. iam:PassRole for the task role and the execution role
        #
        # PRD §2.22: using CfnSchedule (L1) — no stable L2 yet in aws-cdk-lib.
        scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            description="Allow EventBridge Scheduler to launch the inference ECS task",
        )

        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                sid="RunInferenceTask",
                actions=["ecs:RunTask"],
                resources=[self.task_definition.task_definition_arn],
                conditions={
                    "ArnLike": {
                        "ecs:cluster": cluster.cluster_arn,
                    }
                },
            )
        )

        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                sid="PassTaskRoles",
                actions=["iam:PassRole"],
                resources=[
                    self.task_definition.task_role.role_arn,
                    # execution_role is non-null for Fargate tasks
                    self.task_definition.obtain_execution_role().role_arn,
                ],
            )
        )

        # Resolve public subnet IDs at synth time for the network config.
        # CDK context caches AZ lookups in cdk.context.json (committed).
        public_subnets = vpc.select_subnets(subnet_type=ec2.SubnetType.PUBLIC)

        self.schedule = scheduler.CfnSchedule(
            self,
            "InferenceSchedule",
            # Nightly at 03:00 UTC — adjust INFERENCE_SCHEDULE_EXPR in
            # constants.py; no infrastructure.py change needed.
            schedule_expression=constants.INFERENCE_SCHEDULE_EXPR,
            schedule_expression_timezone="UTC",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF",
            ),
            state="ENABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                # For ECS RunTask, the target ARN is the cluster ARN.
                arn=cluster.cluster_arn,
                role_arn=scheduler_role.role_arn,
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=self.task_definition.task_definition_arn,
                    task_count=1,
                    launch_type="FARGATE",
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=public_subnets.subnet_ids,
                            security_groups=[self.task_sg.security_group_id],
                            # Public IP required in default VPC without VPC endpoints
                            # (ECR image pull goes over the internet). See PRD §6.6.
                            assign_public_ip="ENABLED",
                        ),
                    ),
                ),
                # No input override — the task reads all config from env vars.
                input=json.dumps({}),
            ),
        )
