# Enterprise ML Platform

A production-grade Machine Learning platform built from scratch to manage the operational lifecycle of ML models. It bridges the gap between notebook models and reliable cloud services by providing reproducible, auditable, and safely iterable infrastructure — engineered independently, not a wrapper around SageMaker.

Total AWS spend to build and validate v1–v2: **~$2**.

## System Architecture

The platform is organized into a stateful data plane and a stateless control plane. It is entirely codified in AWS CDK (Python) and isolated within private VPC subnets, fronted by an Application Load Balancer and NAT Gateway for strict network security.

* **Model Catalog API (FastAPI):** A CQRS REST API that serves as the boundary between data scientists and the underlying infrastructure. State is managed via SQLModel and Alembic async migrations on an RDS Postgres database.
* **Feature Store (Feast):** S3 for offline point-in-time joins and DynamoDB for low-latency online serving. This dual-store pattern structurally eliminates training-serving skew and label leakage.
* **Experiment Tracking (MLflow):** Deployed on ECS Fargate with an RDS Postgres backend. Tracks lineage and utilizes atomic alias promotion for model deployment without container redeploys.
* **Decoupled Compute (ECS Fargate):** Isolated task definitions for bursty training workloads and lean batch inference runs, orchestrated dynamically via EventBridge schedules.

## Roadmap

* **v1 — Shipped:** Single-model infra — Feast + MLflow + Fargate training/inference, EventBridge scheduling.
* **v2 — Shipped:** Multi-model catalog — FastAPI CQRS API, SQLModel + Alembic on RDS, network hardening (ALB/NAT).
* **v3 — In progress:** The Training Subsystem — Developer loop optimization (3-second local mocking) and pipeline hardening.
* **v4 — Planned:** The Inference Subsystem — Hardening batch pipelines and transitioning to real-time online serving (BentoML).
* **v5 — Planned:** The Application Layer — Deploying complex real-world case studies (e.g. causal inference, anomaly detection).
* **v6 — Planned:** The Monitoring Subsystem — Data drift detection, prediction tracking, and observability.
* **v7 — Planned:** The Capstone — Next.js UI integration and web dashboard.

## Quickstart

To deploy the platform to your AWS sandbox account, ensure your Docker daemon is running and your AWS CLI is authenticated.

```bash
# Sync infrastructure and development dependencies
uv sync --group infra

# Deploy the stateful data plane and stateless control plane
make deploy

# Tear down all resources cleanly when finished
make destroy
```

For full end-to-end execution, synthetic data generation, and API validation, follow the [Deployment Guide](docs/deployment-guide.md).

## Engineering Documentation

This repository is documented for technical leaders and platform engineers. The engineering logs detail the rationale, alternatives considered, and cost tradeoffs for every architectural component.

* **[Architectural Decision Log](docs/ml-platform-prd.md)**: Documents 27 engineering decisions covering network hardening, IAM least-privilege scoping, and database state management.
* **[Dependency Architecture](docs/dependency-architecture.md)**: Details the multi-stage Docker build pattern and `uv` dependency group isolation that prevents CDK infrastructure libraries from bloating runtime ML containers.
* **[Deployment Guide](docs/deployment-guide.md)**: Step-by-step instructions for live AWS deployment, synthetic data generation, and end-to-end ML execution.
* **[Road to Prod](docs/road-to-prod.md)**: The roadmap for multi-user collaboration, BentoML online serving, and continuous data drift monitoring.

## Technical Blog Series

The design philosophy and development of this platform are documented in a series of deep dives focused on systems engineering for ML.

* **Part 1:** [Beyond the Notebook: The Operational Reality of an Enterprise ML Platform](https://danivpv.com/blog/beyond-the-notebook)
* **Part 2:** [The API Boundary: Enterprise Networking and Stateful ML Orchestration](https://danivpv.com/blog/the-api-boundary-and-stateful-orchestration)

## Tech Stack

* **Cloud & Infrastructure:** AWS CDK, ECS Fargate, S3, DynamoDB, RDS Postgres, Application Load Balancer, NAT Gateway, EventBridge, CloudWatch.
* **Runtime & APIs:** Python 3.12, FastAPI, SQLModel, Alembic, Docker.
* **ML Operations:** Feast, MLflow, Scikit-Learn.
* **Tooling:** `uv` for deterministic dependency resolution and multi-stage container builds.

---

**Daniel Iván Parra Verde** — ML Engineer specializing in production AI systems and ML platforms. [Portfolio](https://danivpv.com) · [Blog](https://danivpv.com/blog) · [LinkedIn](https://linkedin.com/in/danivpv)
