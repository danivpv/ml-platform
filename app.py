#!/usr/bin/env python3
"""
app.py — CDK app entry point.

Instantiates two stacks:
  MLPlatformStateful   — stateful data plane (S3, DynamoDB, RDS, ECS Cluster)
  MLPlatformStateless  — compute + observability (Fargate tasks, EventBridge,
                          CloudWatch dashboard + alarms)

Deploy:
  uv run cdk synth
  uv run cdk deploy --all --profile <sandbox-profile>

To deploy stacks individually (stateful first, stateless depends on it):
  uv run cdk deploy MLPlatformStateful --profile <sandbox-profile>
  uv run cdk deploy MLPlatformStateless --profile <sandbox-profile>

See SETUP.md for the required pre-deploy checklist.
"""

import aws_cdk as cdk

import constants
from ml_platform.component import MLPlatformStatefulStack, MLPlatformStatelessStack

app = cdk.App()

env = cdk.Environment(
    account=constants.ACCOUNT,
    region=constants.REGION,
)

stateful = MLPlatformStatefulStack(
    app,
    "MLPlatformStateful",
    env=env,
    description="ML Platform — stateful data plane (S3, DynamoDB, RDS)",
    # Termination protection: set to True before any production use.
    # Leaving False for sandbox iteration convenience.
    termination_protection=False,
)

stateless = MLPlatformStatelessStack(
    app,
    "MLPlatformStateless",
    stateful=stateful,
    env=env,
    description="ML Platform — compute and observability (Fargate, EventBridge, CloudWatch)",
    termination_protection=False,
)

# Explicit dependency: CloudFormation deploys stateful before stateless.
stateless.add_dependency(stateful)

# Apply global cost-tracking tags recursively to all resources in the application.
cdk.Tags.of(app).add("Project", constants.APP_NAME)
cdk.Tags.of(app).add("Environment", constants.STAGE)

app.synth()
