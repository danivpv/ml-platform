#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering API & MLflow Gateway (ALB) URL..."
ALB_URL=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='ApiEndpointUrl'].OutputValue" --output text)
echo "ALB Gateway: ${ALB_URL}"

echo "==> 2. Updating SSM Parameter Store with ALB URL..."
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name "/ml-platform/sandbox/mlflow-tracking-uri" --value "${ALB_URL}" --overwrite --profile default >/dev/null

echo ""
echo "============================================================"
echo "🎯 OPEN MLFLOW UI IN BROWSER (COPY & PASTE THIS):"
echo "${ALB_URL}"
echo "============================================================"
