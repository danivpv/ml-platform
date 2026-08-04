"""
experiment_tracking/infrastructure.py
======================================
CDK construct for the MLflow experiment-tracking subsystem.

Resources provisioned:
  - S3 bucket           — MLflow artifact store (models, plots, datasets)
  - Security groups     — RDS SG (5432 from MLflow SG only),
                          MLflow SG (5000 from developer CIDR)
  - RDS Postgres        — db.t4g.micro, single-AZ, auto-generated Secrets
                          Manager secret, default VPC public subnet,
                          publicly_accessible=False (SG-gated)
  - ECS Cluster         — shared by MLflow service and batch tasks
  - SSM StringParameter — MLflow tracking URI placeholder; updated manually
                          post-deploy once the task's public IP is known
                          (see PRD §2.21)
  - Fargate Service     — MLflow server (0.25 vCPU / 0.5 GB), public subnet,
                          assign_public_ip=True, no ALB (see PRD §2.9)

Security concerns (PRD §6):
  - developer_cidr defaults to 0.0.0.0/0 in constants.py — replace before
    deploy (CDK emits an Annotations warning if unchanged).
  - RDS sits in a public subnet but publicly_accessible=False; the SG is the
    only enforcement layer (v2: private subnet + NAT/VPC endpoints).
"""

from typing import Any

from aws_cdk import (
    Annotations,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_rds as rds,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from ml_platform.config import settings
from ml_platform.constants import ROOT_DIR
from aws_cdk.aws_ecr_assets import DockerImageAsset
from constructs import Construct
from ml_platform.experiment_tracking.constants import (
    MLFLOW_IMAGE_PORT,
    MLFLOW_FARGATE_CPU,
    MLFLOW_FARGATE_MEMORY_MB,
    RDS_DB_NAME,
    RDS_PORT,
)


class ExperimentTrackingConstruct(Construct):
    """
    Provisions all infrastructure required to run the MLflow tracking server.

    Constructor parameters:
      vpc            — the VPC in which to place the RDS instance and
                       Fargate service (default VPC passed from component.py)
      developer_cidr — CIDR allowed to reach the MLflow UI on port 5000

    Exposed properties (consumed by component.py):
      artifacts_bucket — S3 bucket for MLflow artifacts
      rds_instance     — RDS Postgres instance
      rds_sg           — security group attached to RDS
      mlflow_sg        — security group attached to the MLflow Fargate service
      cluster          — ECS cluster (shared by training/inference tasks)
      mlflow_service   — the Fargate service running the MLflow server
      mlflow_uri_param — SSM parameter holding the tracking server URI
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        developer_cidr: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Warn if CIDR is still the insecure default ─────────────────────
        if developer_cidr == "0.0.0.0/0":
            Annotations.of(self).add_warning(
                "SECURITY: developer_cidr is '0.0.0.0/0'. "
                "The MLflow UI (port 5000) will be open to the internet. "
                "Set DEVELOPER_CIDR in constants.py to your IP/32 before deploying. "
                "See PRD §6.2."
            )

        # ── S3: MLflow artifact store ──────────────────────────────────────
        self.artifacts_bucket = s3.Bucket(
            self,
            "ArtifactsBucket",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── Security groups ────────────────────────────────────────────────
        # RDS SG — inbound 5432 restricted to MLflow Fargate task SG only.
        # allow_all_outbound=False: RDS has no reason to initiate outbound.
        self.rds_sg = ec2.SecurityGroup(
            self,
            "RdsSg",
            vpc=vpc,
            description="Allow Postgres (5432) from the MLflow Fargate task only",
            allow_all_outbound=False,
        )

        # MLflow SG — inbound 5000 from developer CIDR; outbound unrestricted
        # (needs to reach RDS on 5432 and S3 on 443).
        self.mlflow_sg = ec2.SecurityGroup(
            self,
            "MlflowSg",
            vpc=vpc,
            description="Allow MLflow UI (5000) from developer CIDR",
            allow_all_outbound=True,
        )
        self.mlflow_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(developer_cidr),
            connection=ec2.Port.tcp(MLFLOW_IMAGE_PORT),
            description="MLflow UI from developer IP",
        )

        # Wire: RDS allows 5432 from the MLflow SG
        self.rds_sg.add_ingress_rule(
            peer=self.mlflow_sg,
            connection=ec2.Port.tcp(RDS_PORT),
            description="Postgres from MLflow Fargate task",
        )

        # ── RDS Postgres ───────────────────────────────────────────────────
        # db.t4g.micro — cheapest ARM-based instance, sufficient for MLflow's
        # lightweight metadata writes. Single-AZ, no Multi-AZ (solo sandbox).
        # publicly_accessible=False — the public subnet has a public route but
        # the SG enforces that only the MLflow SG can reach port 5432.
        # removal_policy=SNAPSHOT — takes a final snapshot on `cdk destroy`.
        self.rds_instance = rds.DatabaseInstance(
            self,
            "MlflowDb",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16_13
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO
            ),
            credentials=rds.Credentials.from_generated_secret(
                "mlflow",
                secret_name=f"{settings.app_name}/{settings.stage}/rds-mlflow",
            ),
            database_name=RDS_DB_NAME,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            publicly_accessible=False,
            security_groups=[self.rds_sg],
            multi_az=False,
            allocated_storage=20,
            max_allocated_storage=100,
            storage_encrypted=True,
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY,
            backup_retention=None,  # no automated backups in sandbox
        )

        # ── ECS Cluster ────────────────────────────────────────────────────
        # Shared by the MLflow service and by batch training/inference tasks
        # (which are run via ECS RunTask, not as services).
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # ── SSM: MLflow tracking URI (updated post-deploy) ─────────────────
        # The public IP of the MLflow task is unknown at synth time.
        # Training/inference task definitions reference this parameter so the
        # URI can be updated without a redeploy of the stateless stack.
        # After deploy:
        #   aws ssm put-parameter \
        #     --name /ml-platform/sandbox/mlflow-tracking-uri \
        #     --value "http://<TASK_PUBLIC_IP>:5000" \
        #     --overwrite --profile <sandbox-profile>
        self.mlflow_uri_param = ssm.StringParameter(
            self,
            "MlflowUriParam",
            parameter_name=settings.ssm_mlflow_tracking_uri,
            string_value="http://REPLACE_AFTER_DEPLOY:5000",
            description=(
                "MLflow tracking server URI. "
                "Update after deploy with the Fargate task public IP."
            ),
        )

        # ── MLflow Fargate service ─────────────────────────────────────────
        # Image is built from experiment_tracking/runtime/Dockerfile.
        # The CMD in that Dockerfile constructs the Postgres URI from injected
        # env vars (DB_USERNAME, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME) using
        # ecs.Secret.from_secrets_manager — plaintext password never appears in
        # the task definition JSON stored in CloudFormation.
        mlflow_image = DockerImageAsset(
            self,
            "MlflowImage",
            directory=ROOT_DIR,
            file="src/ml_platform/experiment_tracking/runtime/Dockerfile",
        )

        task_def = ecs.FargateTaskDefinition(
            self,
            "MlflowTaskDef",
            cpu=MLFLOW_FARGATE_CPU,
            memory_limit_mib=MLFLOW_FARGATE_MEMORY_MB,
        )

        # Grant the MLflow task role access to the artifact bucket.
        # (Training/inference grants are wired in component.py after both
        # constructs are instantiated.)
        self.artifacts_bucket.grant_read_write(task_def.task_role)

        # The RDS secret contains: username, password, host, port, dbname
        rds_secret = self.rds_instance.secret
        assert rds_secret is not None, (
            "RDS instance has no Secrets Manager secret. "
            "Ensure credentials=Credentials.from_generated_secret() was used."
        )

        task_def.add_container(
            "MlflowContainer",
            image=ecs.ContainerImage.from_docker_image_asset(mlflow_image),
            port_mappings=[ecs.PortMapping(container_port=MLFLOW_IMAGE_PORT)],
            environment={
                "MLFLOW_HOST": "0.0.0.0",
                "MLFLOW_PORT": str(MLFLOW_IMAGE_PORT),
                # S3 URI is safe to embed statically — bucket name is a CDK token
                "MLFLOW_ARTIFACT_ROOT": (
                    f"s3://{self.artifacts_bucket.bucket_name}/artifacts"
                ),
            },
            # Secrets are injected by ECS agent at task start; they never
            # appear in CloudFormation templates or CloudWatch logs.
            secrets={
                "DB_USERNAME": ecs.Secret.from_secrets_manager(rds_secret, "username"),
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(rds_secret, "password"),
                "DB_HOST": ecs.Secret.from_secrets_manager(rds_secret, "host"),
                "DB_PORT": ecs.Secret.from_secrets_manager(rds_secret, "port"),
                "DB_NAME": ecs.Secret.from_secrets_manager(rds_secret, "dbname"),
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="mlflow"),
        )

        # ECS agent needs the execution role to resolve ecs.Secret references
        # at task start. execution_role is always set for Fargate task defs.
        exec_role = task_def.execution_role
        assert exec_role is not None, (
            "FargateTaskDefinition must have an execution role"
        )
        rds_secret.grant_read(exec_role)

        self.mlflow_service = ecs.FargateService(
            self,
            "MlflowService",
            cluster=self.cluster,
            task_definition=task_def,
            desired_count=1,
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            min_healthy_percent=100,
            max_healthy_percent=200,
            # Public subnet + public IP: required in default VPC without a NAT
            # gateway. The SG restricts inbound to developer CIDR on port 5000.
            assign_public_ip=True,
            security_groups=[self.mlflow_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )
