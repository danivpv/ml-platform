#!/usr/bin/env bash
set -eo pipefail

echo "==> 1. Discovering Feature Bucket and Online DynamoDB Table..."
export FEATURE_BUCKET=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='FeatureBucketName'].OutputValue" --output text)
export ONLINE_TABLE=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='OnlineTableName'].OutputValue" --output text)

echo "Feature Bucket: $FEATURE_BUCKET"
echo "Online Table: $ONLINE_TABLE"

echo "==> 2. Applying Feast feature definitions..."
uv run --no-default-groups --group inference-training feast -c src/ml_platform/feature_store/runtime/feature_repo apply
