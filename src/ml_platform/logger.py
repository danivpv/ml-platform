"""
logger.py
=========================
Structured JSON logging setup for all runtime containers.

All runtime containers (training, inference) call configure_logging() at
startup so every log record is emitted as a JSON object. This enables
CloudWatch Logs Insights to query fields like level, message, run_id, etc.
without regex parsing.

Usage:
  from ml_platform.logger import configure_logging
  configure_logging()  # call once at the top of main()
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


class _JsonFormatter(logging.Formatter):
    """
    Formats each LogRecord as a single-line JSON object.

    Standard fields emitted:
      timestamp — ISO-8601 UTC
      level     — DEBUG / INFO / WARNING / ERROR / CRITICAL
      logger    — logger name
      message   — formatted log message
      module    — source module name
      line      — source line number

    Extra fields passed via `extra={}` in logging calls are merged in at the
    top level so CloudWatch Logs Insights can filter on them directly.
    """

    # Fields that LogRecord always has; excluded from the "extra" merge.
    _RESERVED = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "module": record.module,
            "line": record.lineno,
        }

        # Merge caller-supplied extra fields.
        for key, value in record.__dict__.items():
            if key not in self._RESERVED:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = traceback.format_exception(*record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure the root logger to emit structured JSON to stdout.

    Should be called exactly once at the top of each container's main().
    Idempotent — subsequent calls are no-ops if the root logger already has
    handlers configured.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    # Suppress noisy third-party loggers at WARNING unless we're in DEBUG.
    if level > logging.DEBUG:
        for noisy in ("botocore", "urllib3", "s3transfer", "boto3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
