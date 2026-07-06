#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering ECS Cluster, Batch Inference Task Definition, Security Group, and Feature Bucket..."
CLUSTER=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" --output text)
SUBNET=$(aws ec2 describe-subnets --filters "Name=defaultForAz,Values=true" --profile default --query "Subnets[0].SubnetId" --output text)
FEATURE_BUCKET=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='FeatureBucketName'].OutputValue" --output text)
INF_TASK_DEF=$(aws cloudformation describe-stacks --stack-name MLPlatformStateless --profile default --query "Stacks[0].Outputs[?OutputKey=='InferenceTaskDefinitionArn'].OutputValue" --output text)
INF_SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=*MLPlatformStateless*InferenceSg*" --profile default --query "SecurityGroups[0].GroupId" --output text)

echo "==> 2. Launching Batch Inference ECS Task..."
INF_ARN=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$INF_TASK_DEF" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$INF_SG],assignPublicIp=ENABLED}" --profile default --query "tasks[0].taskArn" --output text)
echo "Inference Task launched: $INF_ARN"

echo "==> 3. Waiting for batch inference container to finish (~2-3 mins: includes Fargate ENI provisioning + ECR pull + scoring)..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$INF_ARN" --profile default

echo "==> 4. Verifying prediction output files in S3..."
aws s3 ls "s3://${FEATURE_BUCKET}/predictions/" --recursive --profile default

MLFLOW_TASK_ARN=$(aws ecs list-tasks --cluster "$CLUSTER" --profile default --query "taskArns[0]" --output text)
ENI_ID=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$MLFLOW_TASK_ARN" --profile default --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text)
PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI_ID" --profile default --query "NetworkInterfaces[0].Association.PublicIp" --output text)

echo ""
echo "============================================================"
echo "🎯 VIEW INFERENCE RUN & METRICS IN BROWSER:"
echo "http://${PUBLIC_IP}:5000"
echo "============================================================"
