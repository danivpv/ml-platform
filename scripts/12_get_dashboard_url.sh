#!/usr/bin/env bash
set -eo pipefail

echo "==> Discovering CloudWatch Monitoring Dashboard URL..."
DASHBOARD_URL=$(aws cloudformation describe-stacks --stack-name MLPlatformStateless --profile default --query "Stacks[0].Outputs[?OutputKey=='MonitoringDashboardUrl'].OutputValue" --output text)

echo ""
echo "============================================================"
echo "📊 CLOUDWATCH INFRASTRUCTURE DASHBOARD:"
echo "$DASHBOARD_URL"
echo "============================================================"
