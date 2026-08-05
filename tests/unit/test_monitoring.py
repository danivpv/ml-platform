"""
tests/unit/test_monitoring.py
================================
CDK assertions tests for MonitoringConstruct.

Run:  uv run pytest tests/unit/test_monitoring.py -v
"""

import aws_cdk as cdk
import pytest
from aws_cdk import (
    assertions,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_rds as rds,
)

from ml_platform.monitoring.infrastructure import MonitoringConstruct

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
        },
        {
            "name": "Private",
            "type": "Private",
            "subnets": [
                {
                    "subnetId": "subnet-priv1",
                    "cidr": "10.0.1.0/24",
                    "availabilityZone": "us-east-1a",
                    "routeTableId": "rtb-2",
                }
            ],
        },
    ],
}


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App(context={_VPC_CONTEXT_KEY: _MOCK_VPC_CONTEXT})
    env = cdk.Environment(account="123456789012", region="us-east-1")
    stack = cdk.Stack(app, "TestStack", env=env)

    vpc = ec2.Vpc.from_lookup(stack, "Vpc", is_default=True)

    cluster = ecs.Cluster(stack, "Cluster", vpc=vpc)

    # Minimal FargateTaskDefinition + FargateService to satisfy MonitoringConstruct
    task_def = ecs.FargateTaskDefinition(
        stack, "TaskDef", cpu=256, memory_limit_mib=512
    )
    task_def.add_container(
        "Container",
        image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
    )
    mlflow_service = ecs.FargateService(
        stack,
        "MlflowService",
        cluster=cluster,
        task_definition=task_def,
        assign_public_ip=True,
        vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
    )

    rds_sg = ec2.SecurityGroup(stack, "RdsSg", vpc=vpc)
    rds_instance = rds.DatabaseInstance(
        stack,
        "RdsInstance",
        engine=rds.DatabaseInstanceEngine.postgres(
            version=rds.PostgresEngineVersion.VER_16_13
        ),
        instance_type=ec2.InstanceType.of(
            ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO
        ),
        vpc=vpc,
        security_groups=[rds_sg],
        vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
    )

    online_table = dynamodb.Table(
        stack,
        "OnlineTable",
        partition_key=dynamodb.Attribute(
            name="entity_id", type=dynamodb.AttributeType.STRING
        ),
    )

    MonitoringConstruct(
        stack,
        "Monitoring",
        mlflow_service=mlflow_service,
        rds_instance=rds_instance,
        online_table=online_table,
        alarm_email="test@example.com",
    )
    return assertions.Template.from_stack(stack)


class TestSnsTopicAndSubscription:
    def test_sns_topic_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::SNS::Topic", 1)

    def test_email_subscription_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::SNS::Subscription", 1)

    def test_subscription_protocol_email(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::SNS::Subscription",
            {"Protocol": "email", "Endpoint": "test@example.com"},
        )


class TestCloudWatchAlarms:
    def test_four_alarms_exist(self, template: assertions.Template) -> None:
        """Exactly 4 alarms: MLflow CPU, MLflow Mem, RDS CPU, DynamoDB throttles."""
        template.resource_count_is("AWS::CloudWatch::Alarm", 4)

    def test_mlflow_cpu_alarm(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "MLPlatform-MLflow-CPU-High",
                "Threshold": 80,
                "EvaluationPeriods": 5,
            },
        )

    def test_mlflow_mem_alarm(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "MLPlatform-MLflow-Memory-High",
                "Threshold": 80,
                "EvaluationPeriods": 5,
            },
        )

    def test_rds_cpu_alarm(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "MLPlatform-RDS-CPU-High",
                "Threshold": 80,
                "EvaluationPeriods": 5,
            },
        )

    def test_dynamo_throttle_alarm(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "MLPlatform-DynamoDB-Throttles",
                "Threshold": 0,
                "EvaluationPeriods": 1,
            },
        )

    def test_all_alarms_notify_sns(self, template: assertions.Template) -> None:
        """Each alarm has at least one AlarmAction wired to the SNS topic."""
        alarms = template.find_resources("AWS::CloudWatch::Alarm")
        for alarm_id, alarm in alarms.items():
            actions = alarm.get("Properties", {}).get("AlarmActions", [])
            assert len(actions) >= 1, (
                f"Alarm {alarm_id!r} has no AlarmActions (not wired to SNS)"
            )


class TestCloudWatchDashboard:
    def test_dashboard_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::CloudWatch::Dashboard", 1)

    def test_dashboard_name(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::CloudWatch::Dashboard",
            {"DashboardName": "MLPlatform-Infra-Health"},
        )
