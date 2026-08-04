"""
tests/unit/test_training.py
============================
CDK assertions tests for TrainingConstruct.

Run:  uv run pytest tests/unit/test_training.py -v
"""

import aws_cdk as cdk
import pytest
from aws_cdk import (
    assertions,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_s3 as s3,
    aws_ssm as ssm,
)

from ml_platform.training.constants import TASK_CPU, TASK_MEMORY_MB
from ml_platform.training.infrastructure import TrainingConstruct

_VPC_CONTEXT_KEY = (
    "vpc-provider:account=123456789012:filter.isDefault=true"
    ":region=us-east-1:returnAsymmetricSubnets=true"
)
_MOCK_VPC_CONTEXT = {
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


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App(context={_VPC_CONTEXT_KEY: _MOCK_VPC_CONTEXT})
    env = cdk.Environment(account="123456789012", region="us-east-1")
    stack = cdk.Stack(app, "TestStack", env=env)

    vpc = ec2.Vpc.from_lookup(stack, "Vpc", is_default=True)
    cluster = ecs.Cluster(stack, "Cluster", vpc=vpc)

    # Minimal stub resources to satisfy TrainingConstruct's constructor
    bucket = s3.Bucket(stack, "FeatureBucket")
    table = dynamodb.Table(
        stack,
        "OnlineTable",
        partition_key=dynamodb.Attribute(
            name="entity_id", type=dynamodb.AttributeType.STRING
        ),
    )
    artifacts_bucket = s3.Bucket(stack, "ArtifactsBucket")
    uri_param = ssm.StringParameter(
        stack,
        "MlflowUriParam",
        string_value="http://PLACEHOLDER:5000",
    )

    TrainingConstruct(
        stack,
        "Training",
        cluster=cluster,
        vpc=vpc,
        feature_bucket_name=bucket.bucket_name,
        online_table_name=table.table_name,
        artifacts_bucket_name=artifacts_bucket.bucket_name,
        mlflow_uri_param=uri_param,
    )
    return assertions.Template.from_stack(stack)


class TestTrainingTaskDefinition:
    def test_task_definition_exists(self, template: assertions.Template) -> None:
        # stack has cluster task def + training task def = >=1
        template.resource_count_is("AWS::ECS::TaskDefinition", 1)

    def test_task_cpu(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Cpu": str(TASK_CPU)},
        )

    def test_task_memory(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Memory": str(TASK_MEMORY_MB)},
        )

    def test_task_requires_fargate(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"RequiresCompatibilities": ["FARGATE"]},
        )

    def test_task_network_mode_awsvpc(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"NetworkMode": "awsvpc"},
        )

    def test_container_log_config(self, template: assertions.Template) -> None:
        """Container uses awslogs driver with 'training' prefix."""
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {
                "ContainerDefinitions": assertions.Match.array_with(
                    [
                        assertions.Match.object_like(
                            {
                                "LogConfiguration": {
                                    "LogDriver": "awslogs",
                                    "Options": assertions.Match.object_like(
                                        {"awslogs-stream-prefix": "training"}
                                    ),
                                }
                            }
                        )
                    ]
                )
            },
        )


class TestTrainingSecurityGroup:
    def test_sg_exists(self, template: assertions.Template) -> None:
        # At minimum 1 SG for the training task
        sgs = template.find_resources(
            "AWS::EC2::SecurityGroup",
            {
                "Properties": {
                    "GroupDescription": assertions.Match.string_like_regexp(
                        ".*Training.*"
                    )
                }
            },
        )
        assert len(sgs) >= 1, "No training task security group found"

    def test_no_inbound_rules(self, template: assertions.Template) -> None:
        """Training task SG has no ingress rules (outbound-only)."""
        sgs = template.find_resources(
            "AWS::EC2::SecurityGroup",
            {
                "Properties": {
                    "GroupDescription": assertions.Match.string_like_regexp(
                        ".*Training.*outbound.*"
                    )
                }
            },
        )
        for sg in sgs.values():
            ingress = sg.get("Properties", {}).get("SecurityGroupIngress", [])
            assert ingress == [], f"Training SG has unexpected ingress rules: {ingress}"
