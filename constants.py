"""
constants.py — single source of truth for tunables across all CDK constructs.

Anything that might differ between environments (region, CIDRs, sizes,
schedules) lives here. Never hardcode these values inside infrastructure.py
files — always import from this module.
"""

import os

# ── Identity ───────────────────────────────────────────────────────────────
APP_NAME = "ml-platform"
STAGE = os.environ.get("STAGE", "sandbox")

# CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION are injected by the CDK CLI when
# the app is synthesised with `--profile` or the AWS_PROFILE env var is set.
ACCOUNT = os.environ.get("CDK_DEFAULT_ACCOUNT") or os.environ.get("AWS_ACCOUNT_ID") or "975050146846"
REGION = os.environ.get("CDK_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

# ── Networking ─────────────────────────────────────────────────────────────
# ⚠  SECURITY: Replace with your actual IP before `cdk deploy`.
#    Run:  curl -s ifconfig.me
#    Then: set DEVELOPER_CIDR = "<your-ip>/32"
# Leaving this as 0.0.0.0/0 exposes the MLflow UI to the internet (see PRD §6.2).
DEVELOPER_CIDR = "187.156.66.153/32"

# ── MLflow Fargate service ─────────────────────────────────────────────────
MLFLOW_IMAGE_PORT = 5000
MLFLOW_FARGATE_CPU = 512  # 0.5 vCPU
MLFLOW_FARGATE_MEMORY_MB = 2048

# ── Training / Inference Fargate tasks ────────────────────────────────────
TASK_CPU = 512  # 0.5 vCPU
TASK_MEMORY_MB = 1024

# ── RDS ───────────────────────────────────────────────────────────────────
RDS_DB_NAME = "mlflowdb"
RDS_PORT = 5432

# ── Inference schedule ─────────────────────────────────────────────────────
# EventBridge Scheduler cron expression — nightly at 03:00 UTC.
# Adjust here; no change to infrastructure.py required.
INFERENCE_SCHEDULE_EXPR = "cron(0 3 * * ? *)"

# ── Monitoring ────────────────────────────────────────────────────────────
# Email address that receives CloudWatch alarm notifications.
# ⚠  REPLACE before deploy — SNS will send a subscription-confirmation email.
ALARM_EMAIL = "danivpv@outlook.com"

# ── SSM parameter names ───────────────────────────────────────────────────
# After deploy: retrieve the MLflow task's public IP from ECS console, then run:
#   aws ssm put-parameter \
#     --name /ml-platform/sandbox/mlflow-tracking-uri \
#     --value "http://<IP>:5000" \
#     --overwrite --profile <sandbox-profile>
SSM_MLFLOW_TRACKING_URI = f"/{APP_NAME}/{STAGE}/mlflow-tracking-uri"
