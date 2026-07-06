"""
tests/unit/test_inference.py
==============================
CDK assertions tests for InferenceConstruct.

Run:  uv run pytest tests/unit/test_inference.py -v
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

import constants
from ml_platform.inference.infrastructure import InferenceConstruct

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

    InferenceConstruct(
        stack,
        "Inference",
        cluster=cluster,
        vpc=vpc,
        feature_bucket_name=bucket.bucket_name,
        online_table_name=table.table_name,
        artifacts_bucket_name=artifacts_bucket.bucket_name,
        mlflow_uri_param=uri_param,
    )
    return assertions.Template.from_stack(stack)


class TestInferenceTaskDefinition:
    def test_task_definition_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::ECS::TaskDefinition", 1)

    def test_task_cpu(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Cpu": str(constants.TASK_CPU)},
        )

    def test_task_memory(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Memory": str(constants.TASK_MEMORY_MB)},
        )

    def test_container_log_config(self, template: assertions.Template) -> None:
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
                                        {"awslogs-stream-prefix": "inference"}
                                    ),
                                }
                            }
                        )
                    ]
                )
            },
        )


class TestEventBridgeScheduler:
    def test_schedule_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::Scheduler::Schedule", 1)

    def test_schedule_expression(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::Scheduler::Schedule",
            {"ScheduleExpression": constants.INFERENCE_SCHEDULE_EXPR},
        )

    def test_schedule_timezone_utc(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::Scheduler::Schedule",
            {"ScheduleExpressionTimezone": "UTC"},
        )

    def test_schedule_state_enabled(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::Scheduler::Schedule",
            {"State": "ENABLED"},
        )

    def test_schedule_fargate_launch_type(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::Scheduler::Schedule",
            {
                "Target": assertions.Match.object_like(
                    {
                        "EcsParameters": assertions.Match.object_like(
                            {"LaunchType": "FARGATE"}
                        )
                    }
                )
            },
        )

    def test_schedule_assigns_public_ip(self, template: assertions.Template) -> None:
        """Inference task needs a public IP for ECR pull in the default VPC."""
        template.has_resource_properties(
            "AWS::Scheduler::Schedule",
            {
                "Target": assertions.Match.object_like(
                    {
                        "EcsParameters": assertions.Match.object_like(
                            {
                                "NetworkConfiguration": assertions.Match.object_like(
                                    {
                                        "AwsvpcConfiguration": assertions.Match.object_like(
                                            {"AssignPublicIp": "ENABLED"}
                                        )
                                    }
                                )
                            }
                        )
                    }
                )
            },
        )


class TestSchedulerIamRole:
    def test_scheduler_role_exists(self, template: assertions.Template) -> None:
        roles = template.find_resources(
            "AWS::IAM::Role",
            {
                "Properties": {
                    "AssumeRolePolicyDocument": assertions.Match.object_like(
                        {
                            "Statement": assertions.Match.array_with(
                                [
                                    assertions.Match.object_like(
                                        {
                                            "Principal": {
                                                "Service": "scheduler.amazonaws.com"
                                            }
                                        }
                                    )
                                ]
                            )
                        }
                    )
                }
            },
        )
        assert len(roles) >= 1, "No scheduler IAM role found"

    def test_scheduler_role_allows_ecs_run_task(
        self, template: assertions.Template
    ) -> None:
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {"Action": "ecs:RunTask", "Effect": "Allow"}
                            )
                        ]
                    )
                }
            },
        )

    def test_scheduler_role_allows_iam_pass_role(
        self, template: assertions.Template
    ) -> None:
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {"Action": "iam:PassRole", "Effect": "Allow"}
                            )
                        ]
                    )
                }
            },
        )
