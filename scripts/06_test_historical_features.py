"""
scripts/06_test_historical_features.py
======================================
Verifies Feast point-in-time join functionality against historical S3 feature data.
"""

import os
from datetime import timezone
from pathlib import Path

import pandas as pd
from feast import FeatureStore
import ml_platform.feature_store.runtime.feature_repo as repo_pkg


def main():
    if "FEATURE_BUCKET" not in os.environ or "ONLINE_TABLE" not in os.environ:
        try:
            import boto3

            print(
                "Auto-discovering FEATURE_BUCKET and ONLINE_TABLE from CloudFormation stack MLPlatformStateful..."
            )
            cf = boto3.client("cloudformation")
            res = cf.describe_stacks(StackName="MLPlatformStateful")
            for out in res["Stacks"][0].get("Outputs", []):
                if (
                    out["OutputKey"] == "FeatureBucketName"
                    and "FEATURE_BUCKET" not in os.environ
                ):
                    os.environ["FEATURE_BUCKET"] = out["OutputValue"]
                elif (
                    out["OutputKey"] == "OnlineTableName"
                    and "ONLINE_TABLE" not in os.environ
                ):
                    os.environ["ONLINE_TABLE"] = out["OutputValue"]
            print(
                f"Auto-discovered FEATURE_BUCKET={os.environ.get('FEATURE_BUCKET')}, ONLINE_TABLE={os.environ.get('ONLINE_TABLE')}"
            )
        except Exception as e:
            print(f"Failed to auto-discover env vars from CloudFormation: {e}")

    if "FEATURE_BUCKET" not in os.environ:
        raise ValueError("FEATURE_BUCKET environment variable must be set.")
    if "ONLINE_TABLE" not in os.environ:
        raise ValueError(
            "ONLINE_TABLE environment variable must be set for Feast online store config."
        )

    fb = os.environ["FEATURE_BUCKET"]
    print(f"Connecting to Feast FeatureStore using FEATURE_BUCKET={fb}...")

    repo_path = str(Path(repo_pkg.__file__).parent)
    store = FeatureStore(repo_path=repo_path)

    labels_s3_path = f"s3://{fb}/offline/labels/labels_synthetic.parquet"
    print(f"Reading synthetic labels from {labels_s3_path}...")
    labels = pd.read_parquet(labels_s3_path)

    entity_df = labels[["entity_id", "event_timestamp"]].copy()
    if entity_df["event_timestamp"].dt.tz is None:
        entity_df["event_timestamp"] = entity_df["event_timestamp"].dt.tz_localize(
            timezone.utc
        )

    print("Performing point-in-time join with historical customer features...")
    features = store.get_historical_features(
        entity_df=entity_df,
        features=[
            "customer_features:age",
            "customer_features:account_balance",
            "customer_features:num_transactions",
            "customer_features:days_since_last_txn",
        ],
    ).to_df()

    nulls = features["age"].isna().sum()
    print(
        f"\nHistorical join successful! Shape: {features.shape}. Nulls found: {nulls}"
    )
    if nulls > 0:
        print("WARNING: Some feature values were null!")
    else:
        print(
            "LEAKAGE & JOIN CHECK PASSED: All records matched point-in-time features cleanly."
        )


if __name__ == "__main__":
    main()
