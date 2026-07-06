# ML Platform MVP — Live Deployment & Validation Guide

**Author:** Daniel Iván Parra Verde 
**Scope:** Step-by-step live AWS infrastructure deployment, pedagogical Feature Store validation, end-to-end ML training/inference execution, and security/cost verification.

---

## 📖 Pedagogical Overview: How This Platform Works

This ML Platform is designed around **SOLID principles**, **fail-fast data contracts**, and a **two-stack CDK topology** separating persistent data from ephemeral compute:

1. **Stateful Stack (`MLPlatformStateful`)**: Houses resources with data retention policies (S3 feature & artifact buckets, DynamoDB online store, RDS Postgres metadata DB, ECS Cluster).
2. **Stateless Stack (`MLPlatformStateless`)**: Houses compute and observability (Training Fargate task definition, Batch Inference Fargate task & EventBridge Scheduler, CloudWatch Alarms & Dashboards). Because it is stateless, you can iterate on task definitions or schedules without ever risking your data plane.

### 🧠 The Core Feast Feature Store Concepts
Feast operates in two distinct phases that novice users often confuse:
* **`feast apply` (Metadata Registration)**: Reads your Python feature definitions (`entities.py`, `feature_views.py`) and writes a schema snapshot (`registry.db`) to S3. **No feature data is moved.** It simply acts as a schema migration so Feast knows where the raw Parquet files live in S3 and what DynamoDB table to target.
* **`feast materialize-incremental` (Data Sync)**: Reads the raw offline Parquet files from S3, filters for records up to the current timestamp, and writes the latest single feature value per entity into DynamoDB. This prepares the low-latency online store for point-in-time or real-time lookups.

---

## Phase 1: Infrastructure Synthesis & Deployment

### Step 1: Synthesise CloudFormation Templates
Before deploying, verify that your CDK Python code translates cleanly into AWS CloudFormation JSON templates:
```bash
make synth
```
*Expected output: `Successfully synthesized to C:\...\cdk.out` with no cyclic dependency errors.*

### Step 2: Deploy Both Stacks
Deploy the stateful data plane first, followed by the stateless compute control plane:
```bash
make deploy
```
*(Takes ~10-15 minutes on first run due to ECR image pushes and RDS provisioning).*

### Step 3: Post-Deploy Configuration (MLflow Tracking URI & SNS)
Discover the dynamically assigned MLflow Fargate private/public IPs and register the internal URI in AWS Systems Manager (SSM) Parameter Store:
```bash
bash scripts/03_post_deploy_config.sh
```
*Check your browser at `http://<PUBLIC_IP>:5000` to confirm the MLflow UI loads.*

> **📧 SNS Alarm Confirmation:** Check your email inbox for a message from `AWS Notifications` titled **"AWS Notification - Subscription Confirmation"**. Click **Confirm subscription** so CloudWatch infrastructure alarms can reach you.

---

## Phase 2: Data & Feature Store Validation

### Step 4: Generate Synthetic Data & Verify Anti-Leakage
Generate synthetic customer data (ensuring feature timestamps are strictly older than label timestamps) and upload Parquet files to S3:
```bash
uv run --no-default-groups --group inference-training python scripts/04_generate_synthetic_data.py
```
*Expected log: `LEAKAGE CHECK PASSED: all 200 entities satisfy feature_ts < label_ts.` Followed by successful uploads to `s3://<bucket>/offline/...`.*

### Step 5: Feature Store Registration (`feast apply`)
Register feature definitions with S3 so Feast knows the offline and online schema:
```bash
bash scripts/05_feast_apply.sh
```
*Expected log: `Registry written to s3://<bucket>/registry/registry.db`.*

> **⚠️ AWS Eventual Consistency Gotcha (`LimitExceededException`):** If you run Step 5 immediately after `make deploy`, DynamoDB may reject tagging requests with `Table tags are being updated`. AWS locks DynamoDB tables asynchronously for 30–60 seconds after stack creation while propagating tags across partitions. If this occurs, simply wait 30 seconds and re-run the script.

### Step 6: Verify Historical Feature Retrieval (Point-in-Time Join)
Verify that Feast can join historical features against label timestamps without dropping future rows:
```bash
uv run --no-default-groups --group inference-training python scripts/06_test_historical_features.py
```
*Expected output: `Historical join successful! Shape: (200, 6). Nulls found: 0` followed by `LEAKAGE & JOIN CHECK PASSED`.*

### Step 7: Online Feature Materialisation (`feast materialize-incremental`)
Sync the latest offline records from S3 into DynamoDB for low-latency scoring lookups:
```bash
bash scripts/07_feast_materialize.sh
```
*Expected log: `Materializing 1 feature views to <END_DATE> into the dynamodb online store... 100%|█████████| 200/200`.*

---

## Phase 3: End-to-End ML Execution

### Step 8: Trigger Training Fargate Task
Launch the containerized Scikit-Learn training task in ECS to train the model, log metrics/artifacts to MLflow, and assign the `@champion` alias:
```bash
bash scripts/08_trigger_training.sh
```
*Expected execution time: **~2 to 3 minutes**.*
> **💡 Why 2–3 minutes instead of 30 seconds?** Previous estimates measured only pure Python compute execution (~10s). In serverless cloud environments, AWS Fargate incurs a one-time cold-start overhead: allocating hypervisor compute resources, attaching a VPC Elastic Network Interface (ENI ~40s), and pulling the container image from ECR over the network (~40s).

*Open your MLflow UI (`http://<PUBLIC_IP>:5000`) to verify the new run, logged metrics (`accuracy`, `f1_score`, `roc_auc`), and registered model `ml-platform-churn@champion`.*
*(Note: In V1, we log the PyFunc model artifact, parameters, and metrics without attaching explicit MLflow Model Signatures [input/output schema] or markdown run descriptions. This keeps V1 minimal and focused on pipeline plumbing; model signatures and metadata enrichment are planned for V2).*

### Step 9: Run Batch Inference & Verify Idempotency
Trigger the batch inference container to score offline/online features against the `@champion` model and write timestamped JSONL predictions back to S3:
```bash
bash scripts/09_trigger_inference.sh
```
*Expected execution time: **~2 to 3 minutes** (includes Fargate ENI provisioning + ECR image download + DynamoDB/S3 scoring reads).*
*Expected output: A file named `predictions_<YYYYMMDDTHHMMSSZ>.jsonl` containing 200 valid prediction JSON records.*

> **🔄 Idempotency Check:** Running Step 9 multiple times creates **new** timestamped files in `s3://<bucket>/predictions/` rather than overwriting previous predictions, preventing data loss in production pipelines.

### Step 10: Verify Model Portability
Confirm that the model logged by the training task can be downloaded from MLflow and scored outside the ECS container:
```bash
bash scripts/10_test_model_portability.sh
```
*Expected log: `MODEL PORTABILITY CHECK PASSED!`*

---

## Phase 4: Security, Observability & Cost Hygiene

### Step 11: Least-Privilege IAM Scope Check
Verify via AWS IAM simulation that container task roles enforce least-privilege (e.g., ensuring inference tasks cannot delete raw feature data):
```bash
bash scripts/11_test_iam_policies.sh
```
*Expected log: `✅ IAM LEAST-PRIVILEGE CHECK PASSED!`*

### Step 12: Observability & CloudWatch Dashboard
Retrieve the URL for your pre-configured CloudWatch Dashboard to monitor Fargate CPU/Memory spikes and DynamoDB throttling:
```bash
bash scripts/12_get_dashboard_url.sh
```

### Step 13: Cost Hygiene & Teardown
To prevent ongoing AWS charges when you finish testing:

| Action | Command / Instruction |
|---|---|
| **Stop MLflow Compute** (Scales Fargate tasks to 0; RDS/S3 retain state) | `aws ecs update-service --cluster $CLUSTER --service MlflowService --desired-count 0 --profile default` |
| **Stop RDS Database** | AWS Console → RDS → Select `mlflowdb` → Actions → **Stop** |
| **Resume RDS Database** | AWS Console → RDS → Select `mlflowdb` → Actions → **Start** |
| **Full Decommissioning** | `uv run cdk destroy --all --profile default` |

> **✨ Note on Clean Decommissioning:** Every storage resource in this infrastructure (`FeatureBucket`, `ArtifactsBucket`, `OnlineStore` DynamoDB table, and `mlflowdb` RDS instance) is explicitly configured with **`RemovalPolicy.DESTROY`** and **`auto_delete_objects=True`**. Running `cdk destroy` will cleanly wipe 100% of all AWS resources, buckets, tables, and data without leaving orphaned resources or ongoing charges!
