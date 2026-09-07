"""Structured JSON logger for CloudWatch.

Every Lambda uses this to produce consistent, queryable log entries.
The agent's CloudWatch tool parses these fields to correlate failures.
"""

import json
import logging
import os
import time
from typing import Any


logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = os.environ.get("SERVICE_NAME", "unknown")


def log_event(
    status: str,
    message: str,
    latency_ms: float = 0,
    dependency: str | None = None,
    error_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a structured JSON log entry to CloudWatch.

    Args:
        status: One of 'success', 'error', 'timeout', 'degraded'.
        message: Human-readable description.
        latency_ms: Duration of the operation in milliseconds.
        dependency: Name of the downstream service or resource involved.
        error_type: Classification like 'connection_refused', 'timeout', 'auth_failed'.
        extra: Additional key-value pairs for context.
    """
    entry = {
        "timestamp": time.time(),
        "service": SERVICE_NAME,
        "status": status,
        "message": message,
        "latency_ms": round(latency_ms, 2),
    }

    if dependency:
        entry["dependency"] = dependency
    if error_type:
        entry["error_type"] = error_type
    if extra:
        entry.update(extra)

    logger.info(json.dumps(entry))
