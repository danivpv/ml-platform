# ML Platform MVP — Live Deployment & Validation Guide

**Author:** Daniel Iván Parra Verde 
**Scope:** Step-by-step live AWS infrastructure deployment, Feature Store validation, end-to-end ML training/inference execution, and security/cost verification.

---

## Phase 1: Infrastructure Deployment

### Step 1: Synthesize & Deploy Both Stacks
Deploy the stateful data plane first, followed by the stateless compute control plane (takes ~10-15 minutes on first run):
```bash
make deploy
```

### Step 2: Extract the ALB Endpoint & Post-Deploy Configuration
All external access goes through a single Application Load Balancer (ALB). We save its URL to AWS Systems Manager (SSM) so MLflow and compute tasks can discover it:
```bash
# We export ALB_URL, FEATURE_BUCKET, and ONLINE_TABLE so subsequent commands in this shell session can use them.
export ALB_URL=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='ApiEndpointUrl'].OutputValue" --output text)
export FEATURE_BUCKET=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='FeatureBucketName'].OutputValue" --output text)
export ONLINE_TABLE=$(aws cloudformation describe-stacks --stack-name MLPlatformStateful --profile default --query "Stacks[0].Outputs[?OutputKey=='OnlineTableName'].OutputValue" --output text)

# We save the ALB URL to SSM because the stateless ECS compute tasks (like training) need to discover it dynamically.
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name "/ml-platform/sandbox/mlflow-tracking-uri" --value "${ALB_URL}" --overwrite --profile default >/dev/null
```
*Check your browser at the output URL to confirm the MLflow UI loads securely.*

> **📧 SNS Alarm Confirmation:** Check your email inbox for a message from `AWS Notifications` titled **"AWS Notification - Subscription Confirmation"**. Click **Confirm subscription** so CloudWatch infrastructure alarms can reach you.

---

## Phase 2: Data & Feature Store Validation

### Step 3: Generate Synthetic Data & Verify Anti-Leakage
Generate synthetic customer data (ensuring feature timestamps are strictly older than label timestamps) and upload Parquet files to S3:
```bash
uv run --no-default-groups --group inference-training python scripts/04_generate_synthetic_data.py
```
*Expected log: `LEAKAGE CHECK PASSED: all 200 entities satisfy feature_ts < label_ts.` Followed by successful uploads to S3.*

### Step 4: Feature Store Registration (`feast apply`)
Register feature definitions with S3 so Feast knows the offline and online schema. This is purely a metadata operation (schema migration); no feature data is moved.
```bash
uv run --no-default-groups --group inference-training feast -c src/ml_platform/feature_store/runtime/feature_repo apply
```
*Expected log: `Registry written to s3://<bucket>/registry/registry.db`.*

> **⚠️ AWS Eventual Consistency Gotcha (`LimitExceededException`):** If DynamoDB rejects tagging requests with `Table tags are being updated`, wait 30 seconds and retry.

### Step 5: Verify Historical Feature Retrieval (Point-in-Time Join)
Verify that Feast can join historical features against label timestamps without dropping future rows:
```bash
uv run --no-default-groups --group inference-training python scripts/06_test_historical_features.py
```
*Expected log: `Historical join successful! Shape: (200, 6). Nulls found: 0` followed by `LEAKAGE & JOIN CHECK PASSED`.*

### Step 6: Online Feature Materialisation (`feast materialize-incremental`)
Sync the latest offline records from S3 into DynamoDB. This prepares the low-latency online store for point-in-time or real-time lookups:
```bash
uv run --no-default-groups --group inference-training feast -c src/ml_platform/feature_store/runtime/feature_repo materialize-incremental $(date -u +"%Y-%m-%dT%H:%M:%S")
```
*Expected log: `Materializing 1 feature views to <END_DATE> into the dynamodb online store... 100%|█████████| 200/200`.*

---

## Phase 3: End-to-End ML Execution

### Step 7: Register the Model in the API Catalog
Define the model metadata (features, labels, tracking config) in Postgres via the API.
```bash
curl -X POST "${ALB_URL}/v1/models" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "churn_model",
    "feature_view": "customer_features",
    "feature_refs": "customer_features:age,customer_features:account_balance,customer_features:num_transactions,customer_features:days_since_last_txn",
    "label_column": "churned",
    "mlflow_experiment": "churn_prediction",
    "owner": "data_science_team"
  }'
```
*Expected output: JSON payload echoing the created model with an `id` and `created_at` timestamp.*

### Step 8: Trigger Training Fargate Task via API
Launch the containerized Scikit-Learn training task dynamically.
> **⚠️ Terminal Copy-Paste Gotcha:** Copy the entire `ALB_URL=` command as a single line to avoid `ParameterNotFound` errors.

```bash
curl -X POST "${ALB_URL}/v1/models/churn_model/train" -H "Content-Type: application/json"
```
*Expected output: `{"task_arn": "arn:aws:ecs:...", "cluster_arn": "arn:aws:ecs:..."}` (202 Accepted).*

Poll the `task_arn` to track its progress:
```bash
curl -X GET "${ALB_URL}/v1/tasks/<task_arn_here>"
```
*Expected execution time: **~2 to 3 minutes** to transition from `PROVISIONING` -> `RUNNING` -> `STOPPED` (due to Fargate ENI provisioning + ECR image cold-start).*

*Open your MLflow UI by visiting the **`${ALB_URL}`** in your browser to verify the new run, logged metrics, and registered model **`churn_model@champion`**.*

### Step 9: Run Batch Inference & Verify Idempotency
Trigger the batch inference container via the Catalog API to score features against the `@champion` model:
```bash
curl -X POST "${ALB_URL}/v1/models/churn_model/predict" -H "Content-Type: application/json"
```
*Expected execution time: **~2 to 3 minutes**.*
*Expected output: A file named `predictions_<YYYYMMDDTHHMMSSZ>.jsonl` in S3 containing 200 valid prediction JSON records.*

> **🔄 Idempotency Check:** Verify that running Step 9 multiple times creates **new** timestamped files rather than overwriting previous predictions (preventing data loss):
```bash
aws s3 ls "s3://${FEATURE_BUCKET}/predictions/" --profile default
```

---

## Phase 4: Security, Observability & Cost Hygiene

### Step 10: Observability & CloudWatch Dashboard
Retrieve the URL for your pre-configured CloudWatch Dashboard to monitor Fargate metrics and DynamoDB throttling:
```bash
aws cloudformation describe-stacks --stack-name MLPlatformStateless --profile default --query "Stacks[0].Outputs[?OutputKey=='MonitoringDashboardUrl'].OutputValue" --output text
```

### Step 11: Cost Hygiene & Teardown
To prevent ongoing AWS charges when you finish testing:

| Action | Command / Instruction |
|---|---|
| **Stop MLflow Compute** | `aws ecs update-service --cluster <MLflowCluster> --service MlflowService --desired-count 0 --profile default` |
| **Stop RDS Database** | AWS Console → RDS → Select `mlflowdb` → Actions → **Stop** |
| **Resume RDS Database** | AWS Console → RDS → Select `mlflowdb` → Actions → **Start** |
| **Full Decommissioning** | `make destroy` |

> **✨ Note on Clean Decommissioning:** Every storage resource (`FeatureBucket`, `ArtifactsBucket`, `OnlineStore` DynamoDB, and `mlflowdb` RDS) is explicitly configured with **`RemovalPolicy.DESTROY`** and **`auto_delete_objects=True`**. Running `make destroy` cleanly wipes 100% of all AWS resources without leaving orphaned objects or ongoing charges.
