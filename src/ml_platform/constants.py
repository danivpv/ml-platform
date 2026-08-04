"""
ml_platform/constants.py
===================
Shared CDK infrastructure constants and platform configuration.
"""

from pathlib import Path

# ⚠ SECURITY: Replace with your actual IP before `cdk deploy`.
DEVELOPER_CIDR = "187.156.66.153/32"

ROOT_DIR = str(Path(__file__).resolve().parents[2])
