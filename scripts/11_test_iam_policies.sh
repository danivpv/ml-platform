#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering Batch Inference Task Definition and Feature Bucket..."
INF_TASK_DEF=$(aws cloudformation describe-stacks --stack-name MLPlatformStateless --profile default --query "Stacks[0].Outputs[?OutputKey=='InferenceTaskDefinitionArn'].OutputValue" --output text)
FEATURE_BUCKET=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='FeatureBucketName'].OutputValue" --output text)

echo "==> 2. Getting Inference Task Role ARN..."
INF_ROLE=$(aws ecs describe-task-definition --task-definition "$INF_TASK_DEF" --profile default --query "taskDefinition.taskRoleArn" --output text)
echo "Inference Role: $INF_ROLE"

echo "==> 3. Testing s3:DeleteObject on offline features (Must be DENIED / implicitDeny)..."
DEL_RES=$(aws iam simulate-principal-policy --policy-source-arn "$INF_ROLE" --action-names "s3:DeleteObject" --resource-arns "arn:aws:s3:::${FEATURE_BUCKET}/offline/*" --profile default --query "EvaluationResults[0].EvalDecision" --output text)
echo "DeleteObject Decision: $DEL_RES"

echo "==> 4. Testing s3:PutObject on predictions prefix (Must be ALLOWED)..."
PUT_RES=$(aws iam simulate-principal-policy --policy-source-arn "$INF_ROLE" --action-names "s3:PutObject" --resource-arns "arn:aws:s3:::${FEATURE_BUCKET}/predictions/*" --profile default --query "EvaluationResults[0].EvalDecision" --output text)
echo "PutObject Decision: $PUT_RES"

if [ "$DEL_RES" == "implicitDeny" ] && [ "$PUT_RES" == "allowed" ]; then
    echo "✅ IAM LEAST-PRIVILEGE CHECK PASSED!"
else
    echo "❌ IAM LEAST-PRIVILEGE CHECK FAILED! Expected DeleteObject=implicitDeny, PutObject=allowed."
    exit 1
fi
