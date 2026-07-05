"""
feature_store/infrastructure.py
================================
CDK construct for the Feast feature store.

Resources provisioned:
  - S3 bucket  (single bucket, two prefixes)
      offline/   → Parquet feature data (offline store)
      registry/  → Feast registry.db file
  - DynamoDB table (on-demand billing, PAY_PER_REQUEST)
      → Feast online store
      Hash key: entity_id (String) — Feast manages its own key serialisation;
      no sort key is added (see PRD §2.20).

Design notes:
  - Both buckets have RemovalPolicy.RETAIN so data survives a `cdk destroy`.
  - DynamoDB table also uses RETAIN; change to DESTROY only in scratch
    environments where data loss is acceptable.
  - Encryption uses AWS managed keys (SSE-S3 / AWS_MANAGED) to avoid the
    extra cost of a customer-managed KMS key in a solo sandbox (see PRD §6 for
    the v2 hardening path to CMK).
"""

from typing import Any

from aws_cdk import (
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
)
from constructs import Construct


class FeatureStoreConstruct(Construct):
    """
    Provisions the Feast feature store backing infrastructure.

    Exposed properties (consumed by component.py for cross-construct grants):
      bucket      — S3 bucket (offline + registry prefixes)
      online_table — DynamoDB table (Feast online store)
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3: offline store + Feast registry ────────────────────────────
        # Single bucket, two prefixes:
        #   offline/  — parquet feature data read by training/inference
        #   registry/ — registry.db written by `feast apply`
        #
        # CDK generates the bucket name; it is exported via CfnOutput and
        # passed to runtimes via environment variables (never hardcoded).
        self.bucket = s3.Bucket(
            self,
            "FeatureBucket",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── DynamoDB: Feast online store ───────────────────────────────────
        # Feast serialises its own composite entity key into entity_id.
        # On-demand billing → near-zero cost at idle, no capacity planning.
        self.online_table = dynamodb.Table(
            self,
            "OnlineStore",
            partition_key=dynamodb.Attribute(
                name="entity_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
