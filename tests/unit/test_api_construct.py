"""
tests/unit/test_api_construct.py
================================
Verifies the Catalog API CDK construct generates the correct CloudFormation resources.
"""

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from ml_platform.component import MLPlatformStatefulStack, MLPlatformStatelessStack

_VPC_CONTEXT_KEY = (
    "vpc-provider:account=123456789012:filter.isDefault=true"
    ":region=us-east-1:returnAsymmetricSubnets=true"
)
_MOCK_VPC_CONTEXT = {
    "vpcId": "vpc-12345",
    "vpcCidrBlock": "10.0.0.0/16",
    "ownerAccountId": "123456789012",
    "availabilityZones": ["us-east-1a"],
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
def stateless_stack() -> MLPlatformStatelessStack:
    app = cdk.App(context={_VPC_CONTEXT_KEY: _MOCK_VPC_CONTEXT})
    env = cdk.Environment(account="123456789012", region="us-east-1")
    stateful = MLPlatformStatefulStack(app, "Stateful", env=env)
    return MLPlatformStatelessStack(app, "Stateless", stateful=stateful, env=env)


def test_api_fargate_service_created(stateless_stack: MLPlatformStatelessStack) -> None:
    """Ensure the API Fargate service is provisioned and exposes port 8000."""
    template = assertions.Template.from_stack(stateless_stack)

    # Verify a Fargate Service exists with our expected naming logic
    template.has_resource_properties(
        "AWS::ECS::Service",
        {"LaunchType": "FARGATE"},
    )

    # Verify the Task Definition container exposes port 8000
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {
                            "PortMappings": [
                                {"ContainerPort": 8000, "Protocol": "tcp"}
                            ],
                            # Ensure the environment variables are injected
                            "Environment": assertions.Match.array_with(
                                [
                                    {
                                        "Name": "INFERENCE_TASK_ARN",
                                        "Value": assertions.Match.any_value(),
                                    },
                                ]
                            ),
                        }
                    )
                ]
            )
        },
    )
