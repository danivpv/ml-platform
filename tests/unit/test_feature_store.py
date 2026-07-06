"""
tests/unit/test_feature_store.py
=================================
CDK assertions tests for the FeatureStoreConstruct.

Uses aws_cdk.assertions.Template to verify the synthesised CloudFormation
template without deploying. No AWS credentials required to run these tests.

Run:  uv run pytest tests/unit/test_feature_store.py -v
"""

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from ml_platform.feature_store.infrastructure import FeatureStoreConstruct


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    """Synthesise a minimal stack containing only FeatureStoreConstruct."""
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    FeatureStoreConstruct(stack, "FeatureStore")
    return assertions.Template.from_stack(stack)


class TestS3Bucket:
    def test_bucket_exists(self, template: assertions.Template) -> None:
        """One S3 bucket is created."""
        template.resource_count_is("AWS::S3::Bucket", 1)

    def test_bucket_versioning_enabled(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "VersioningConfiguration": {"Status": "Enabled"},
            },
        )

    def test_bucket_encryption_s3_managed(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                    ]
                }
            },
        )

    def test_bucket_blocks_public_access(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
            },
        )

    def test_bucket_enforces_ssl(self, template: assertions.Template) -> None:
        """BucketPolicy denies HTTP requests (enforce_ssl=True)."""
        template.has_resource_properties(
            "AWS::S3::BucketPolicy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Action": "s3:*",
                                    "Condition": {
                                        "Bool": {"aws:SecureTransport": "false"}
                                    },
                                    "Effect": "Deny",
                                }
                            )
                        ]
                    )
                }
            },
        )

    def test_bucket_destroy_removal_policy(self, template: assertions.Template) -> None:
        """Bucket has DeletionPolicy=Delete for clean teardown during development."""
        template.has_resource(
            "AWS::S3::Bucket",
            {"DeletionPolicy": "Delete", "UpdateReplacePolicy": "Delete"},
        )


class TestDynamoDBTable:
    def test_table_exists(self, template: assertions.Template) -> None:
        template.resource_count_is("AWS::DynamoDB::Table", 1)

    def test_table_hash_key_entity_id(self, template: assertions.Template) -> None:
        """Feast online store uses entity_id as the sole hash key (no sort key)."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "KeySchema": [{"AttributeName": "entity_id", "KeyType": "HASH"}],
                "AttributeDefinitions": [
                    {"AttributeName": "entity_id", "AttributeType": "S"}
                ],
            },
        )

    def test_table_on_demand_billing(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"BillingMode": "PAY_PER_REQUEST"},
        )

    def test_table_pitr_enabled(self, template: assertions.Template) -> None:
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}},
        )

    def test_table_destroy_removal_policy(self, template: assertions.Template) -> None:
        template.has_resource(
            "AWS::DynamoDB::Table",
            {"DeletionPolicy": "Delete", "UpdateReplacePolicy": "Delete"},
        )
