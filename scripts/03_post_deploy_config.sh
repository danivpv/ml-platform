#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering MLflow Fargate task public and private IPs..."
CLUSTER=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" --output text)
MLFLOW_TASK_ARN=$(aws ecs list-tasks --cluster "$CLUSTER" --profile default --query "taskArns[0]" --output text)
ENI_ID=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$MLFLOW_TASK_ARN" --profile default --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text)
PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI_ID" --profile default --query "NetworkInterfaces[0].Association.PublicIp" --output text)
PRIVATE_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI_ID" --profile default --query "NetworkInterfaces[0].PrivateIpAddress" --output text)
echo "MLflow Private URI (for containers): http://${PRIVATE_IP}:5000"

echo "==> 2. Updating SSM Parameter Store with private IP..."
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name "/ml-platform/sandbox/mlflow-tracking-uri" --value "http://${PRIVATE_IP}:5000" --overwrite --profile default >/dev/null

echo ""
echo "============================================================"
echo "🎯 OPEN MLFLOW UI IN BROWSER (COPY & PASTE THIS):"
echo "http://${PUBLIC_IP}:5000"
echo "============================================================"
