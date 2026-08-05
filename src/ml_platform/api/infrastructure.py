"""
api/infrastructure.py
======================
CDK construct for the Catalog API Fargate service.

Resources provisioned:
  - Fargate TaskDefinition and Service (FastAPI)
  - Security group for the API
  - IAM role grants:
      - scheduler:CreateSchedule, UpdateSchedule, DeleteSchedule
      - iam:PassRole for the batch inference scheduler role

The API dynamically schedules batch inference via EventBridge Scheduler.
"""

from typing import Any, cast

from aws_cdk import (
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_logs,
    aws_secretsmanager as secretsmanager,
    aws_ssm as ssm,
)
from aws_cdk.aws_ecr_assets import DockerImageAsset
from constructs import Construct

from ml_platform.api.constants import TASK_CPU, TASK_MEMORY_MB
from ml_platform.config import settings
from ml_platform.constants import ROOT_DIR


class ApiConstruct(Construct):
    """
    Provisions the FastAPI catalog and serving gateway service.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster: ecs.Cluster,
        vpc: ec2.IVpc,
        rds_secret: secretsmanager.ISecret,
        training_task_arn: str,
        training_task_role_arn: str,
        training_exec_role_arn: str,
        training_sg_id: str,
        inference_task_arn: str,
        inference_task_role_arn: str,
        inference_exec_role_arn: str,
        inference_sg_id: str,
        inference_scheduler_role_arn: str,
        mlflow_uri_param: ssm.StringParameter,
        alb_listener: elbv2.ApplicationListener,
        alb_sg: ec2.SecurityGroup,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.cluster = cluster

        # ── Security Group ────────────────────────────────────────────────
        self.api_sg = ec2.SecurityGroup(
            self,
            "ApiSg",
            vpc=vpc,
            description="Catalog API security group",
            allow_all_outbound=True,
        )

        # Allow inbound traffic from the ALB on port 8000
        self.api_sg.add_ingress_rule(
            peer=alb_sg,
            connection=ec2.Port.tcp(8000),
            description="Allow API access from ALB",
        )

        # ── Task Definition ───────────────────────────────────────────────
        api_image = DockerImageAsset(
            self,
            "ApiImage",
            directory=ROOT_DIR,
            file="src/ml_platform/api/runtime/Dockerfile",
        )

        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "ApiTaskDef",
            cpu=TASK_CPU,
            memory_limit_mib=TASK_MEMORY_MB,
        )

        db_name = ecs.Secret.from_secrets_manager(rds_secret, "dbname")
        db_username = ecs.Secret.from_secrets_manager(rds_secret, "username")
        db_password = ecs.Secret.from_secrets_manager(rds_secret, "password")
        db_host = ecs.Secret.from_secrets_manager(rds_secret, "host")
        db_port = ecs.Secret.from_secrets_manager(rds_secret, "port")

        # Subnet string resolution
        private_subnets = ",".join(
            [
                s.subnet_id
                for s in vpc.select_subnets(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ).subnets
            ]
        )

        log_group = aws_logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name=f"/ml-platform/{settings.stage}/api",
            removal_policy=RemovalPolicy.DESTROY,
            retention=aws_logs.RetentionDays.ONE_MONTH,
        )

        self.task_definition.add_container(
            "ApiContainer",
            image=ecs.ContainerImage.from_docker_image_asset(api_image),
            environment={
                "INFERENCE_SCHEDULER_ROLE_ARN": inference_scheduler_role_arn,
                "ECS_CLUSTER_NAME": cluster.cluster_name,
                "ECS_CLUSTER_ARN": cluster.cluster_arn,
                "TRAINING_TASK_ARN": training_task_arn,
                "TRAINING_SG_ID": training_sg_id,
                "INFERENCE_TASK_ARN": inference_task_arn,
                "INFERENCE_SG_ID": inference_sg_id,
                "PRIVATE_SUBNETS": private_subnets,
            },
            secrets={
                "DB_USERNAME": db_username,
                "DB_PASSWORD": db_password,
                "DB_HOST": db_host,
                "DB_PORT": db_port,
                "DB_NAME": db_name,
                "MLFLOW_TRACKING_URI": ecs.Secret.from_ssm_parameter(mlflow_uri_param),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="api",
                log_group=log_group,
            ),
            port_mappings=[ecs.PortMapping(container_port=8000)],
        )

        # Grant access to the RDS secret and MLflow URI param
        exec_role = self.task_definition.execution_role
        assert exec_role is not None
        rds_secret.grant_read(exec_role)
        mlflow_uri_param.grant_read(self.task_definition.task_role)

        # Grant EventBridge Scheduler permissions to the API task role
        cast(iam.Role, self.task_definition.task_role).add_to_policy(
            iam.PolicyStatement(
                sid="EventBridgeSchedulerPermissions",
                actions=[
                    "scheduler:CreateSchedule",
                    "scheduler:UpdateSchedule",
                    "scheduler:DeleteSchedule",
                    "scheduler:GetSchedule",
                ],
                resources=["*"],  # Schedule ARNs are dynamic
            )
        )
        cast(iam.Role, self.task_definition.task_role).add_to_policy(
            iam.PolicyStatement(
                sid="PassRoleForTasks",
                actions=["iam:PassRole"],
                resources=[
                    inference_scheduler_role_arn,
                    training_task_role_arn,
                    training_exec_role_arn,
                    inference_task_role_arn,
                    inference_exec_role_arn,
                ],
            )
        )
        cast(iam.Role, self.task_definition.task_role).add_to_policy(
            iam.PolicyStatement(
                sid="RunAndDescribeTasks",
                actions=["ecs:RunTask", "ecs:DescribeTasks"],
                resources=["*"],  # Necessary for cluster-level RunTask execution
            )
        )

        # ── Fargate Service ───────────────────────────────────────────────
        self.api_service = ecs.FargateService(
            self,
            "ApiService",
            cluster=cluster,
            task_definition=self.task_definition,
            desired_count=1,
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            min_healthy_percent=100,
            max_healthy_percent=200,
            assign_public_ip=False,
            security_groups=[self.api_sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
        )

        # Priority rule: route /v1/* to the Catalog API
        alb_listener.add_targets(
            "ApiTarget",
            port=8000,
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/v1/*", "/docs*", "/openapi*"])],
            targets=[
                self.api_service.load_balancer_target(
                    container_name="ApiContainer", container_port=8000
                )
            ],
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200-399",
            ),
        )
