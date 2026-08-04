"""
tests/unit/test_experiment_tracking.py
========================================
CDK assertions tests for ExperimentTrackingConstruct.

Run:  uv run pytest tests/unit/test_experiment_tracking.py -v
"""

import aws_cdk as cdk
import pytest
from aws_cdk import assertions, aws_ec2 as ec2

from ml_platform.constants import SSM_MLFLOW_TRACKING_URI
from ml_platform.experiment_tracking.constants import (
    MLFLOW_FARGATE_CPU,
    MLFLOW_FARGATE_MEMORY_MB,
)
from ml_platform.experiment_tracking.infrastructure import (
    ExperimentTrackingConstruct,
)


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App(
        context={
            # Provide a mock VPC context so from_lookup doesn't fail in
            # a unit test (no AWS credentials available).
            "vpc-provider:account=123456789012:filter.isDefault=true:region=us-east-1:returnAsymmetricSubnets=true": {
                "vpcId": "vpc-12345",
                "vpcCidrBlock": "10.0.0.0/16",
                "ownerAccountId": "123456789012",
                "availabilityZones": [],
                "subnetGroups": [
                    {
                        "name": "Public",
                        "type": "Public",
                        "subnets": [
                            {
                                "subnetId": "subnet-pub1",
                                "cidr": "10.0.0.0/24",
                                "availabilityZone": "us-east-1a",
                                "routeTableId": "rtb-1",
                            }
                        ],
                    }
                ],
            }
        }
    )
    stack = cdk.Stack(
        app,
        "TestStack",
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    vpc = ec2.Vpc.from_lookup(stack, "Vpc", is_default=True)
    ExperimentTrackingConstruct(
        stack,
        "ExperimentTracking",
        vpc=vpc,
        developer_cidr="192.0.2.1/32",  # TEST-NET — safe for unit tests
    )
    return assertions.Template.from_stack(stack)


class TestArtifactsBucket:
    def test_bucket_exists(self, template: assertions.Template) -> None:
        # At least one bucket (the artifacts bucket)
        template.resource_count_is("AWS::S3::Bucket", 1)

    def test_bucket_versioned(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {"VersioningConfiguration": {"Status": "Enabled"}},
        )

    def test_bucket_destroy(self, template: assertions.Template) -> None:
        template.has_resource(
            "AWS::S3::Bucket",
            {"DeletionPolicy": "Delete"},
        )


class TestRdsInstance:
    def test_rds_instance_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::RDS::DBInstance", 1)

    def test_rds_engine_postgres(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"Engine": "postgres"},
        )

    def test_rds_instance_class_t4g_micro(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"DBInstanceClass": "db.t4g.micro"},
        )

    def test_rds_not_multi_az(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"MultiAZ": False},
        )

    def test_rds_storage_encrypted(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"StorageEncrypted": True},
        )

    def test_rds_destroy_removal_policy(self, template: assertions.Template) -> None:
        template.has_resource(
            "AWS::RDS::DBInstance",
            {"DeletionPolicy": "Delete"},
        )

    def test_rds_not_publicly_accessible(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"PubliclyAccessible": False},
        )


class TestEcsCluster:
    def test_cluster_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::ECS::Cluster", 1)

    def test_container_insights_enabled(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::Cluster",
            {"ClusterSettings": [{"Name": "containerInsights", "Value": "enabled"}]},
        )


class TestMlflowService:
    def test_fargate_service_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::ECS::Service", 1)

    def test_fargate_desired_count_one(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::Service",
            {"DesiredCount": 1},
        )

    def test_fargate_launch_type(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::Service",
            {"LaunchType": "FARGATE"},
        )

    def test_fargate_task_definition_cpu(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Cpu": str(MLFLOW_FARGATE_CPU)},
        )

    def test_fargate_task_definition_memory(
        self, template: assertions.Template
    ) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Memory": str(MLFLOW_FARGATE_MEMORY_MB)},
        )


class TestSsmParameter:
    def test_ssm_parameter_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::SSM::Parameter", 1)

    def test_ssm_parameter_name(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::SSM::Parameter",
            {"Name": SSM_MLFLOW_TRACKING_URI},
        )
