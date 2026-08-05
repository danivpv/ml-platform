# Path to Production

Companion to `ml-platform-prd.md`. This is the v2+ roadmap defining the future epics required to scale the ML Platform for multi-user collaboration and production readiness.

## Epic 1: Developer Experience & Collaboration

- **Agentic Workflows:** Set up `.agents` skills to automate routine ML platform tasks, documentation updates, and reviews.
- **Local Development:** Add `docker compose` to mock the platform API, RDS database, and MLflow locally without deploying to AWS.
- **CI/CD & Gates:** Wire GitHub Actions / CDK Pipelines with PR gates and pre-commit hooks for linting, testing, and automated deployments.
- **Security Basics:** Add Dependabot and low-hanging fruit container CVE scanning (e.g., Trivy) to the CI pipelines.
- **AWS Access & Environments:** Migrate from single IP-locked security groups to IAM Identity Center permission sets. Expand from a single sandbox to dev → staging → prod accounts.

## Epic 2: Standardized Training & Multi-Model Support

- **Real Use Case Implementation:** Introduce a second real-world use case (e.g., fraud detection or pricing) to force the decoupling of our current hardcoded training loops.
- **Training Protocol:** Define a strict `BaseMLModel` protocol and `TrainingDispatcher` so the same ECS training container can dynamically pull features and train any conformant model using metadata from the catalog.
- **Reproducibility:** Pin the training data snapshot (anchor `get_historical_features()` to a fixed timestamp) and log dependency lockfile hashes on the MLflow run.

## Epic 3: Advanced Lifecycle & UI Consumption

- **Promotion Mechanism:** Migrate to MLflow model aliases (`@champion`, `@challenger`) rather than fixed stages.
- **Approval Gates:** Implement automated sign-off before an alias moves (e.g., don't reassign `@champion` unless the new version beats the current one on a validation set).
- **API Enhancements:** Extend the strict REST API boundary with:
  - `POST /v1/models/{name}/promote` → Reassign `@champion` alias (with validation gate).
  - `DELETE /v1/models/{name}/champion` → Roll back to the previous version via alias reassignment.
  - **Next.js Integration:** Build a high-level Next.js web application for real-time model interaction, prediction debugging, and catalog discovery.

## Epic 4: Online Serving

- **BentoML Online Serving:** Deploy an online serving endpoint on ECS Fargate that can dynamically load and serve multiple MLflow models concurrently. This provides framework-level process isolation (preventing one memory leak from crashing all models) and horizontal scaling without paying a 200MB base RAM tax per model.
- **Online Feature Retrieval:** Utilize Feast's DynamoDB online store (`get_online_features()`) for real-time, low-latency feature lookups during inference.


## Epic 5: Model Monitoring & Validation

- **Drift & Performance Tracking:** Implement continuous monitoring to detect feature drift and accuracy decay (this tells you when a model has silently gone stale).
- **Input Validation:** Extend runtime pydantic schemas with strict sanity bounds (not just types) so adversarial or malformed inputs are rejected before they reach the scoring layer.

## Epic 6: Deep Security Hardening

- **WAF & HTTPS:** Add ACM-issued TLS and AWS WAF fronting the Application Load Balancer to protect the API boundary from abuse.
- **IAM Boundaries:** Eliminate remaining wildcard resource ARNs (e.g., scoping `ecs:RunTask` and `scheduler:CreateSchedule`).
- **Data Protection:** Enforce SSE-KMS with customer-managed keys (CMK) on S3 buckets holding sensitive training data.

## Epic 7: Long-Term Data Platform & ETL Integration

In v1 and v2, feature engineering is handled via lightweight domain ETL scripts that output Parquet files to the offline S3 bucket. As the platform scales, this evolves into a formal Data Platform integration:
- **Dedicated Transformation Engines:** Replacing single-node scripts with scalable ETL pipelines (e.g., AWS Glue, EMR Spark, or dbt on Snowflake/Redshift) that run on automated cron schedules.
- **Data Quality & Schema Contracts:** Automated data validation (e.g., Great Expectations) enforcing nullity, type checks, and distribution bounds before allowing Feast to ingest.
- **Cross-Team Feature Governance:** Decoupling raw data preparation from ML training jobs entirely, enabling data engineering teams to own offline S3 feature generation.
