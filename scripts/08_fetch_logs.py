"""
scripts/08_fetch_logs.py
========================
Fetches the latest CloudWatch logs for a specific service.

Usage:
  uv run python scripts/08_fetch_logs.py <service>

Services:
  - api
  - mlflow
  - training
  - inference

Example:
  uv run python scripts/08_fetch_logs.py api
"""

import argparse
import sys

import boto3

from ml_platform.config import settings


def main():
    parser = argparse.ArgumentParser(description="Fetch CloudWatch logs for a service.")
    parser.add_argument(
        "service",
        choices=["api", "mlflow", "training", "inference"],
        help="The service to fetch logs for.",
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=50,
        help="Number of log lines to fetch (default: 50)",
    )
    args = parser.parse_args()

    log_group_name = f"/ml-platform/{settings.stage}/{args.service}"
    print(f"Fetching logs from: {log_group_name}")

    logs = boto3.client("logs", region_name=settings.region)

    try:
        # We need to find the latest log stream in this group
        response = logs.describe_log_streams(
            logGroupName=log_group_name,
            orderBy="LastEventTime",
            descending=True,
            limit=1,
        )

        streams = response.get("logStreams", [])
        if not streams:
            print("No log streams found for this service yet.")
            return

        latest_stream = streams[0]
        stream_name = latest_stream["logStreamName"]
        print(f"\n--- Latest Stream: {stream_name} ---")

        # Fetch events from the latest stream
        events_response = logs.get_log_events(
            logGroupName=log_group_name,
            logStreamName=stream_name,
            limit=args.lines,
            startFromHead=False,
        )

        events = events_response.get("events", [])
        if not events:
            print("No events found in this stream.")

        for e in events:
            # Events are returned in chronological order
            # (timestamp is milliseconds since epoch, but we just print the message)
            print(e["message"].rstrip())

    except logs.exceptions.ResourceNotFoundException:
        print(f"Error: Log group '{log_group_name}' does not exist.")
        print(
            "This usually means the service hasn't been deployed yet or hasn't started logging."
        )
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching logs: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
