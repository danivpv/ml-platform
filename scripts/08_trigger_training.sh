#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering ECS Cluster, Training Task Definition, Security Group, and Subnet..."
CLUSTER=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" --output text)
TASK_DEF=$(aws cloudformation describe-stacks --stack-name MLPlatformStateless --profile default --query "Stacks[0].Outputs[?OutputKey=='TrainingTaskDefinitionArn'].OutputValue" --output text)
TRAIN_SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=*MLPlatformStateless*TrainingSg*" --profile default --query "SecurityGroups[0].GroupId" --output text)
SUBNET=$(aws ec2 describe-subnets --filters "Name=defaultForAz,Values=true" --profile default --query "Subnets[0].SubnetId" --output text)

echo "==> 2. Launching ECS Training Task..."
TRAIN_TASK_ARN=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$TRAIN_SG],assignPublicIp=ENABLED}" --profile default --query "tasks[0].taskArn" --output text)
echo "Training Task launched: $TRAIN_TASK_ARN"

echo "==> 3. Waiting for container to finish training (~2-3 mins: includes Fargate ENI provisioning + ECR pull + compute)..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TRAIN_TASK_ARN" --profile default
EXIT_CODE=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TRAIN_TASK_ARN" --profile default --query "tasks[0].containers[0].exitCode" --output text)
echo "Training Exit Code: $EXIT_CODE (Expected: 0)"

if [ "$EXIT_CODE" != "0" ]; then
    echo "❌ Training task failed with exit code $EXIT_CODE!"
    exit 1
fi

MLFLOW_TASK_ARN=$(aws ecs list-tasks --cluster "$CLUSTER" --profile default --query "taskArns[0]" --output text)
ENI_ID=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$MLFLOW_TASK_ARN" --profile default --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text)
PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI_ID" --profile default --query "NetworkInterfaces[0].Association.PublicIp" --output text)

echo ""
echo "============================================================"
echo "🎯 VIEW MLFLOW CHAMPION MODEL IN BROWSER:"
echo "http://${PUBLIC_IP}:5000"
echo "============================================================"
