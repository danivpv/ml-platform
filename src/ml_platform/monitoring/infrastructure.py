"""
monitoring/infrastructure.py
==============================
CDK construct for CloudWatch infra-health monitoring.

Resources provisioned:
  - SNS topic + email subscription (placeholder address — confirm post-deploy)
  - CloudWatch Dashboard with three widget groups:
      1. Fargate (MLflow service CPU + memory utilisation)
      2. RDS (CPU utilisation + active connections)
      3. DynamoDB (consumed write capacity + throttled requests)
  - 4 CloudWatch Alarms → SNS topic:
      1. MLflow ECS CPU  > 80 % for 5 min
      2. MLflow ECS Mem  > 80 % for 5 min
      3. RDS CPU         > 80 % for 5 min
      4. DynamoDB throttles > 0 for 1 min (composite: WriteThrottleEvents +
         SystemErrors)

Design notes:
  - Alarms use BREACHING_MISSING to avoid silent failures when no data
    points have been published yet (e.g., when the Fargate service has
    desired_count=0 between sessions).
  - Dashboard widgets use 6-hour default period; adjust in the AWS console
    without a redeploy.
  - Alarm email must be confirmed by clicking the link in the SNS confirmation
    email before alerts will be delivered. See SETUP.md.
  - Costs: ~$0.30/month for 4 alarms + $0 for dashboard. See PRD §4.
"""

from typing import Any

from aws_cdk import (
    Duration,
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_ecs as ecs,
    aws_rds as rds,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
)
from constructs import Construct


class MonitoringConstruct(Construct):
    """
    Provisions the CloudWatch dashboard, alarms, and SNS notification topic.

    Constructor parameters (all keyword-only):
      mlflow_service — FargateService (for CPU/mem metrics)
      rds_instance   — DatabaseInstance (for CPU/connection metrics)
      online_table   — DynamoDB Table (for throttle metrics)
      alarm_email    — email address for SNS alarm notifications (placeholder)

    Exposed properties:
      topic     — SNS topic (add extra subscriptions in component.py if needed)
      dashboard — CloudWatch dashboard
      alarms    — list of the 4 CloudWatch alarms
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        mlflow_service: ecs.FargateService,
        rds_instance: rds.DatabaseInstance,
        online_table: dynamodb.Table,
        alarm_email: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── SNS topic ──────────────────────────────────────────────────────
        self.topic = sns.Topic(
            self,
            "AlarmTopic",
            display_name="ML Platform Infra Alarms",
        )
        # Email subscription — user must confirm the link AWS sends.
        self.topic.add_subscription(subs.EmailSubscription(alarm_email))  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

        # ── Metric helpers ─────────────────────────────────────────────────
        cluster_name = mlflow_service.cluster.cluster_name
        service_name = mlflow_service.service_name

        mlflow_cpu_metric = cw.Metric(
            namespace="AWS/ECS",
            metric_name="CPUUtilization",
            dimensions_map={
                "ClusterName": cluster_name,
                "ServiceName": service_name,
            },
            statistic="Average",
            period=Duration.minutes(1),
        )
        mlflow_mem_metric = cw.Metric(
            namespace="AWS/ECS",
            metric_name="MemoryUtilization",
            dimensions_map={
                "ClusterName": cluster_name,
                "ServiceName": service_name,
            },
            statistic="Average",
            period=Duration.minutes(1),
        )
        rds_cpu_metric = rds_instance.metric_cpu_utilization(
            period=Duration.minutes(1),
            statistic="Average",
        )
        rds_connections_metric = rds_instance.metric(
            "DatabaseConnections",
            period=Duration.minutes(1),
            statistic="Sum",
        )
        dynamo_throttles_metric = online_table.metric(
            "WriteThrottleEvents",
            period=Duration.minutes(1),
            statistic="Sum",
        )
        dynamo_errors_metric = online_table.metric(
            "SystemErrors",
            period=Duration.minutes(1),
            statistic="Sum",
        )

        # ── Alarms ────────────────────────────────────────────────────────
        # BREACHING on MISSING avoids false "OK" when the service is at 0
        # desired count and publishing no data points.
        alarm_action = cw_actions.SnsAction(self.topic)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

        alarm_mlflow_cpu = cw.Alarm(
            self,
            "MlflowCpuAlarm",
            alarm_name="MLPlatform-MLflow-CPU-High",
            alarm_description="MLflow Fargate service CPU > 80% for 5 minutes",
            metric=mlflow_cpu_metric,
            threshold=80,
            evaluation_periods=5,
            datapoints_to_alarm=5,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.BREACHING,
        )
        alarm_mlflow_cpu.add_alarm_action(alarm_action)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

        alarm_mlflow_mem = cw.Alarm(
            self,
            "MlflowMemAlarm",
            alarm_name="MLPlatform-MLflow-Memory-High",
            alarm_description="MLflow Fargate service memory > 80% for 5 minutes",
            metric=mlflow_mem_metric,
            threshold=80,
            evaluation_periods=5,
            datapoints_to_alarm=5,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.BREACHING,
        )
        alarm_mlflow_mem.add_alarm_action(alarm_action)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

        alarm_rds_cpu = cw.Alarm(
            self,
            "RdsCpuAlarm",
            alarm_name="MLPlatform-RDS-CPU-High",
            alarm_description="RDS Postgres CPU > 80% for 5 minutes",
            metric=rds_cpu_metric,
            threshold=80,
            evaluation_periods=5,
            datapoints_to_alarm=5,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.BREACHING,
        )
        alarm_rds_cpu.add_alarm_action(alarm_action)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

        alarm_dynamo_throttles = cw.Alarm(
            self,
            "DynamoThrottleAlarm",
            alarm_name="MLPlatform-DynamoDB-Throttles",
            alarm_description="DynamoDB online store write throttles or system errors",
            metric=dynamo_throttles_metric,
            threshold=0,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        alarm_dynamo_throttles.add_alarm_action(alarm_action)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

        self.alarms = [
            alarm_mlflow_cpu,
            alarm_mlflow_mem,
            alarm_rds_cpu,
            alarm_dynamo_throttles,
        ]

        # ── CloudWatch Dashboard ───────────────────────────────────────────
        self.dashboard = cw.Dashboard(
            self,
            "MlPlatformDashboard",
            dashboard_name="MLPlatform-Infra-Health",
        )

        self.dashboard.add_widgets(
            # ── Row 1: Fargate (MLflow service) ───────────────────────────
            cw.TextWidget(
                markdown="## Fargate — MLflow Service",
                width=24,
                height=1,
            ),
        )
        self.dashboard.add_widgets(
            cw.GraphWidget(
                title="MLflow CPU Utilisation (%)",
                left=[mlflow_cpu_metric],
                left_y_axis=cw.YAxisProps(min=0, max=100),
                width=12,
            ),
            cw.GraphWidget(
                title="MLflow Memory Utilisation (%)",
                left=[mlflow_mem_metric],
                left_y_axis=cw.YAxisProps(min=0, max=100),
                width=12,
            ),
        )

        self.dashboard.add_widgets(
            # ── Row 2: RDS ────────────────────────────────────────────────
            cw.TextWidget(
                markdown="## RDS — Postgres (MLflow backend store)",
                width=24,
                height=1,
            ),
        )
        self.dashboard.add_widgets(
            cw.GraphWidget(
                title="RDS CPU Utilisation (%)",
                left=[rds_cpu_metric],
                left_y_axis=cw.YAxisProps(min=0, max=100),
                width=12,
            ),
            cw.GraphWidget(
                title="RDS Active Connections",
                left=[rds_connections_metric],
                width=12,
            ),
        )

        self.dashboard.add_widgets(
            # ── Row 3: DynamoDB ───────────────────────────────────────────
            cw.TextWidget(
                markdown="## DynamoDB — Feast Online Store",
                width=24,
                height=1,
            ),
        )
        self.dashboard.add_widgets(
            cw.GraphWidget(
                title="DynamoDB Write Throttle Events",
                left=[dynamo_throttles_metric],
                width=12,
            ),
            cw.GraphWidget(
                title="DynamoDB System Errors",
                left=[dynamo_errors_metric],
                width=12,
            ),
        )

        self.dashboard.add_widgets(
            # ── Row 4: Alarm status summary ───────────────────────────────
            cw.TextWidget(
                markdown="## Alarm Status",
                width=24,
                height=1,
            ),
        )
        self.dashboard.add_widgets(
            cw.AlarmStatusWidget(
                title="Active Alarms",
                alarms=self.alarms,
                width=24,
            ),
        )
