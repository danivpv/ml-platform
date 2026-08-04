"""
inference/constants.py
======================
Constants specific to batch inference.
"""

# EventBridge Scheduler cron expression — nightly at 03:00 UTC.
INFERENCE_SCHEDULE_EXPR = "cron(0 3 * * ? *)"

TASK_CPU = 512
TASK_MEMORY_MB = 1024
