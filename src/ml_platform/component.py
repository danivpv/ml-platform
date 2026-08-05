"""
component.py
=============
Composes all ML platform logical units into two CDK stacks.

Stack topology:
  MLPlatformStatefulStack   — stateful resources (data plane)
    ├── FeatureStoreConstruct    (S3 + DynamoDB)
    └── ExperimentTrackingConstruct (S3 + RDS + ECS Cluster + MLflow Service)

  MLPlatformStatelessStack  — compute + observability (control plane)
    ├── TrainingConstruct    (Fargate task def)
    ├── BatchInferenceConstruct   (Fargate task def + EventBridge Scheduler)
    └── MonitoringConstruct  (CloudWatch dashboard + alarms + SNS)

Separation rationale (PRD §2.18):
  Stateful resources carry RemovalPolicy.RETAIN/SNAPSHOT. Separating them
  means iterating on task definitions, dashboards, or schedules never risks
  the data plane. The stateless stack receives CDK cross-stack references
  from the stateful stack at synthesis time (CloudFormation Exports/Imports).

Cross-construct IAM grants:
  All grants that cross logical-unit boundaries are wired here, not inside
  individual infrastructure.py files. This makes the permission surface
  explicit and auditable in one place.

  Training task role:
    - feature_bucket  → grant_read_write   (read offline features, write
                                            materialize output to registry/)
    - artifacts_bucket → grant_read_write  (log models and plots)
    - online_table    → grant_read_write_data (feast materialize)

  Inference task role:
    - feature_bucket  → grant_read          (read offline/  prefix)
    - feature_bucket  → custom write policy (write predictions/ prefix only)
    - artifacts_bucket → grant_read         (load model from registry)
    - online_table    → grant_read_data     (feast get_online_features)

  RDS security group:
    - allow 5432 from training task SG   (training reads MLflow URI from DB
                                          indirectly via the tracking server;
                                          this rule is a v2 preparatory grant
                                          for direct DB access if needed)
    - allow 5432 from inference task SG  (same rationale)

CfnOutputs:
  Stateful stack:  feature bucket name, online table name, artifacts bucket
                   name, RDS secret ARN, SSM MLflow URI parameter name
  Stateless stack: cluster ARN, inference schedule ARN
"""

from typing import Any, cast

from aws_cdk import (
    CfnOutput,
    Stack,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
)
from constructs import Construct

from ml_platform.api.infrastructure import ApiConstruct
from ml_platform.config import settings
from ml_platform.constants import DEVELOPER_CIDR
from ml_platform.experiment_tracking.constants import MLFLOW_IMAGE_PORT, RDS_PORT
from ml_platform.experiment_tracking.infrastructure import (
    ExperimentTrackingConstruct,
)
from ml_platform.feature_store.infrastructure import FeatureStoreConstruct
from ml_platform.inference.batch.infrastructure import InferenceConstruct
from ml_platform.monitoring.constants import ALARM_EMAIL
from ml_platform.monitoring.infrastructure import MonitoringConstruct
from ml_platform.training.infrastructure import TrainingConstruct

# ─────────────────────────────────────────────────────────────────────────────
# Stack 1 — Stateful (data plane)
# ─────────────────────────────────────────────────────────────────────────────


class MLPlatformStatefulStack(Stack):
    """
    Provisions all stateful resources: feature store, experiment tracking.

    Exposes properties that the stateless stack consumes via CDK
    cross-stack references (CloudFormation Exports).
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Networking ─────────────────────────────────────────────────────
        # Provision a custom VPC with 1 NAT Gateway for private subnets.
        # This hardens the network by moving Fargate tasks off public IPs.
        self.vpc = ec2.Vpc(
            self,
            "PlatformVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )
        # ── Application Load Balancer (Ingress Gateway) ────────────────────
        self.alb_sg = ec2.SecurityGroup(
            self,
            "AlbSg",
            vpc=self.vpc,
            description="ALB security group",
            allow_all_outbound=True,
        )
        self.alb_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(DEVELOPER_CIDR),
            connection=ec2.Port.tcp(80),
            description="Allow HTTP access from developer CIDR",
        )

        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "ApiAlb",
            vpc=self.vpc,
            internet_facing=True,
            security_group=self.alb_sg,
        )
        self.listener = self.alb.add_listener("ApiListener", port=80)

        self.feature_store = FeatureStoreConstruct(self, "FeatureStore")
        self.experiment_tracking = ExperimentTrackingConstruct(
            self,
            "ExperimentTracking",
            vpc=self.vpc,
            developer_cidr=DEVELOPER_CIDR,
            alb_listener=self.listener,
            alb_sg=self.alb_sg,
        )
        # rds_instance.secret is always populated by CDK when
        # generate_secret_rotation=True (default for DatabaseInstance).
        rds_secret_ref = self.experiment_tracking.rds_instance.secret
        assert rds_secret_ref is not None, "RDS secret must be set by CDK"

        # ── CfnOutputs ────────────────────────────────────────────────────
        CfnOutput(
            self,
            "FeatureBucketName",
            value=self.feature_store.bucket.bucket_name,
            description="S3 bucket for Feast offline store and registry",
            export_name=f"{settings.app_name}-{settings.stage}-feature-bucket",
        )
        CfnOutput(
            self,
            "OnlineTableName",
            value=self.feature_store.online_table.table_name,
            description="DynamoDB table for Feast online store",
            export_name=f"{settings.app_name}-{settings.stage}-online-table",
        )
        CfnOutput(
            self,
            "ApiEndpointUrl",
            value=f"http://{self.alb.load_balancer_dns_name}",
            description="API Endpoint URL (Application Load Balancer)",
            export_name=f"{settings.app_name}-{settings.stage}-api-url",
        )
        CfnOutput(
            self,
            "ArtifactsBucketName",
            value=self.experiment_tracking.artifacts_bucket.bucket_name,
            description="S3 bucket for MLflow artifacts",
            export_name=f"{settings.app_name}-{settings.stage}-artifacts-bucket",
        )
        CfnOutput(
            self,
            "RdsSecretArn",
            value=rds_secret_ref.secret_arn,
            description=(
                "Secrets Manager ARN for RDS credentials. "
                "Use: aws secretsmanager get-secret-value --secret-id <ARN>"
            ),
        )
        CfnOutput(
            self,
            "MlflowUriParamName",
            value=self.experiment_tracking.mlflow_uri_param.parameter_name,
            description=(
                "SSM parameter name for the MLflow tracking URI. "
                "Update after deploy: "
                "aws ssm put-parameter --name <NAME> --value http://<IP>:5000 --overwrite"
            ),
        )
        CfnOutput(
            self,
            "ClusterArn",
            value=self.experiment_tracking.cluster.cluster_arn,
            description="ECS cluster ARN (shared by MLflow, training, and inference)",
            export_name=f"{settings.app_name}-{settings.stage}-cluster-arn",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Stack 2 — Stateless (control plane)
# ─────────────────────────────────────────────────────────────────────────────


class MLPlatformStatelessStack(Stack):
    """
    Provisions compute resources (training + inference task defs) and
    observability (monitoring dashboard + alarms).

    Receives cross-stack references from MLPlatformStatefulStack via the
    `stateful` constructor parameter.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stateful: MLPlatformStatefulStack,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Retrieve the custom VPC from the stateful stack.
        vpc = stateful.vpc

        feature_bucket = stateful.feature_store.bucket
        online_table = stateful.feature_store.online_table
        artifacts_bucket = stateful.experiment_tracking.artifacts_bucket
        cluster = stateful.experiment_tracking.cluster
        mlflow_uri_param = stateful.experiment_tracking.mlflow_uri_param
        rds_sg = stateful.experiment_tracking.rds_sg
        mlflow_sg = stateful.experiment_tracking.mlflow_sg
        rds_secret = stateful.experiment_tracking.rds_instance.secret
        assert rds_secret is not None, "RDS secret must be set by CDK"

        # ── Training ──────────────────────────────────────────────────────
        self.training = TrainingConstruct(
            self,
            "Training",
            cluster=cluster,
            vpc=vpc,
            feature_bucket_name=feature_bucket.bucket_name,
            online_table_name=online_table.table_name,
            artifacts_bucket_name=artifacts_bucket.bucket_name,
            mlflow_uri_param=mlflow_uri_param,
        )

        # ── Inference ─────────────────────────────────────────────────────
        self.inference = InferenceConstruct(
            self,
            "Inference",
            cluster=cluster,
            vpc=vpc,
            feature_bucket_name=feature_bucket.bucket_name,
            online_table_name=online_table.table_name,
            artifacts_bucket_name=artifacts_bucket.bucket_name,
            mlflow_uri_param=mlflow_uri_param,
        )

        # ── API (Catalog) ─────────────────────────────────────────────────
        self.api = ApiConstruct(
            self,
            "Api",
            cluster=cluster,
            vpc=vpc,
            rds_secret=rds_secret,
            training_task_arn=self.training.task_definition.task_definition_arn,
            training_task_role_arn=self.training.task_definition.task_role.role_arn,
            training_exec_role_arn=cast(
                iam.Role, self.training.task_definition.execution_role
            ).role_arn,
            training_sg_id=self.training.task_sg.security_group_id,
            inference_task_arn=self.inference.task_definition.task_definition_arn,
            inference_task_role_arn=self.inference.task_definition.task_role.role_arn,
            inference_exec_role_arn=cast(
                iam.Role, self.inference.task_definition.execution_role
            ).role_arn,
            inference_sg_id=self.inference.task_sg.security_group_id,
            inference_scheduler_role_arn=self.inference.scheduler_role.role_arn,
            mlflow_uri_param=mlflow_uri_param,
            alb_listener=stateful.listener,
            alb_sg=stateful.alb_sg,
        )

        # ── Cross-construct IAM grants ────────────────────────────────────
        # Training: full read/write on feature bucket and artifacts bucket,
        # plus DynamoDB read/write for feast materialize.
        feature_bucket.grant_read_write(self.training.task_definition.task_role)
        artifacts_bucket.grant_read_write(self.training.task_definition.task_role)
        online_table.grant_read_write_data(self.training.task_definition.task_role)

        # Inference: read features, write predictions prefix only, read
        # artifacts (model loading), read online table.
        feature_bucket.grant_read(self.inference.task_definition.task_role)
        artifacts_bucket.grant_read(self.inference.task_definition.task_role)
        online_table.grant_read_data(self.inference.task_definition.task_role)

        # Inference writes batch predictions to predictions/ prefix only.
        # We layer a narrower AddToResourcePolicy than grant_read_write to
        # avoid granting delete access to the full bucket.
        # cast: task_role is always a concrete Role for Fargate task defs;
        # IRole interface does not expose add_to_policy.
        cast(iam.Role, self.inference.task_definition.task_role).add_to_policy(
            iam.PolicyStatement(
                sid="InferencePredictionsWrite",
                actions=["s3:PutObject"],
                resources=[
                    feature_bucket.arn_for_objects("predictions/*"),
                ],
            )
        )

        # MLflow SG: allow 5000 from training and inference task SGs.
        # Required so containers running inside the VPC can log runs, metrics,
        # artifacts, and load models over HTTP.
        ec2.CfnSecurityGroupIngress(
            self,
            "MlflowIngressFromTraining",
            group_id=mlflow_sg.security_group_id,
            source_security_group_id=self.training.task_sg.security_group_id,
            ip_protocol="tcp",
            from_port=MLFLOW_IMAGE_PORT,
            to_port=MLFLOW_IMAGE_PORT,
            description="MLflow API from training task",
        )
        ec2.CfnSecurityGroupIngress(
            self,
            "MlflowIngressFromInference",
            group_id=mlflow_sg.security_group_id,
            source_security_group_id=self.inference.task_sg.security_group_id,
            ip_protocol="tcp",
            from_port=MLFLOW_IMAGE_PORT,
            to_port=MLFLOW_IMAGE_PORT,
            description="MLflow API from inference task",
        )
        ec2.CfnSecurityGroupIngress(
            self,
            "MlflowIngressFromApi",
            group_id=mlflow_sg.security_group_id,
            source_security_group_id=self.api.api_sg.security_group_id,
            ip_protocol="tcp",
            from_port=MLFLOW_IMAGE_PORT,
            to_port=MLFLOW_IMAGE_PORT,
            description="MLflow API from catalog API task",
        )

        # RDS SG: allow 5432 from training and inference task SGs.
        # These are preparatory rules for v2 direct-DB access; MLflow server
        # is the only current consumer of the DB (already wired in stateful).
        # We use CfnSecurityGroupIngress within the stateless stack (self)
        # rather than rds_sg.add_ingress_rule to prevent CDK from adding a
        # cyclic cross-stack dependency from stateful -> stateless.
        ec2.CfnSecurityGroupIngress(
            self,
            "RdsIngressFromTraining",
            group_id=rds_sg.security_group_id,
            source_security_group_id=self.training.task_sg.security_group_id,
            ip_protocol="tcp",
            from_port=RDS_PORT,
            to_port=RDS_PORT,
            description="Postgres from training task (v2 preparatory)",
        )
        ec2.CfnSecurityGroupIngress(
            self,
            "RdsIngressFromInference",
            group_id=rds_sg.security_group_id,
            source_security_group_id=self.inference.task_sg.security_group_id,
            ip_protocol="tcp",
            from_port=RDS_PORT,
            to_port=RDS_PORT,
            description="Postgres from inference task (v2 preparatory)",
        )
        ec2.CfnSecurityGroupIngress(
            self,
            "RdsIngressFromApi",
            group_id=rds_sg.security_group_id,
            source_security_group_id=self.api.api_sg.security_group_id,
            ip_protocol="tcp",
            from_port=RDS_PORT,
            to_port=RDS_PORT,
            description="Postgres from catalog API task",
        )

        # ── Monitoring ────────────────────────────────────────────────────
        self.monitoring = MonitoringConstruct(
            self,
            "Monitoring",
            mlflow_service=stateful.experiment_tracking.mlflow_service,
            rds_instance=stateful.experiment_tracking.rds_instance,
            online_table=online_table,
            alarm_email=ALARM_EMAIL,
        )

        # ── CfnOutputs ────────────────────────────────────────────────────
        CfnOutput(
            self,
            "TrainingTaskDefinitionArn",
            value=self.training.task_definition.task_definition_arn,
            description=(
                "Training task definition ARN. Run with: "
                "aws ecs run-task --cluster <ClusterArn> "
                "--task-definition <ARN> --launch-type FARGATE "
                "--network-configuration 'awsvpcConfiguration={subnets=[<subnet>],"
                "securityGroups=[<sg>],assignPublicIp=ENABLED}'"
            ),
        )
        CfnOutput(
            self,
            "InferenceTaskDefinitionArn",
            value=self.inference.task_definition.task_definition_arn,
            description="Inference task definition ARN (also used by EventBridge Scheduler)",
        )
        CfnOutput(
            self,
            "InferenceScheduleArn",
            value=self.inference.schedule.attr_arn,
            description="EventBridge Scheduler ARN for nightly inference runs",
        )
        CfnOutput(
            self,
            "MonitoringDashboardUrl",
            value=(
                f"https://{self.region}.console.aws.amazon.com/cloudwatch/home"
                f"#dashboards:name=MLPlatform-Infra-Health"
            ),
            description="CloudWatch dashboard URL for ML Platform infra health",
        )
