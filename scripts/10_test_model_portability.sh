#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering MLflow Fargate task public IP..."
CLUSTER=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" --output text)
MLFLOW_TASK_ARN=$(aws ecs list-tasks --cluster "$CLUSTER" --profile default --query "taskArns[0]" --output text)
ENI_ID=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$MLFLOW_TASK_ARN" --profile default --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text)
PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI_ID" --profile default --query "NetworkInterfaces[0].Association.PublicIp" --output text)

export MLFLOW_TRACKING_URI="http://${PUBLIC_IP}:5000"
echo "Testing model portability against: $MLFLOW_TRACKING_URI"

echo "==> 2. Running portability test..."
uv run --no-default-groups --group mlflow python scripts/10_test_model_portability.py
