"""
scripts/10_test_model_portability.py
==================================
Verifies that the trained champion model can be loaded from MLflow and scored
outside the ECS container environment.
"""

import os
import mlflow.pyfunc
import pandas as pd


def main():
    if "MLFLOW_TRACKING_URI" not in os.environ:
        raise ValueError("MLFLOW_TRACKING_URI environment variable must be set.")

    tracking_uri = os.environ["MLFLOW_TRACKING_URI"]
    print(f"Connecting to MLflow at {tracking_uri}...")
    mlflow.set_tracking_uri(tracking_uri)

    model_uri = "models:/ml-platform-churn@champion"
    print(f"Loading champion model from {model_uri}...")
    model = mlflow.pyfunc.load_model(model_uri)
    print("Model loaded successfully outside container:", type(model))

    print("Running smoke prediction test against sample dataframe...")
    test_df = pd.DataFrame(
        {
            "age": [35],
            "account_balance": [5000.0],
            "num_transactions": [25],
            "days_since_last_txn": [30],
        }
    )
    prediction = model.predict(test_df)
    print("Test prediction score / class:", prediction)
    print("MODEL PORTABILITY CHECK PASSED!")


if __name__ == "__main__":
    main()
