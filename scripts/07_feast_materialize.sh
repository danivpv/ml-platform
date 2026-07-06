#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering Feature Bucket and Online DynamoDB Table..."
export FEATURE_BUCKET=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='FeatureBucketName'].OutputValue" --output text)
export ONLINE_TABLE=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='OnlineTableName'].OutputValue" --output text)

END_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "==> 2. Materializing online features up to $END_DATE..."
uv run --no-default-groups --group inference-training feast -c src/ml_platform/feature_store/runtime/feature_repo materialize-incremental "$END_DATE"
