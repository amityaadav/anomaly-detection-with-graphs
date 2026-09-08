"""CloudWatch log reader tools for the Strands agent.

These tools let the agent pull recent structured logs from the Lambda
services and correlate them with the dependency graph to diagnose
cascading failures.

Every service Lambda writes JSON log entries via shared/logger.py with
fields: timestamp, service, status, message, latency_ms, dependency,
error_type.  The tools here query CloudWatch Logs Insights to surface
errors and latency spikes.
"""

import os
import time

import boto3
from strands import tool


def _get_logs_client():
    return boto3.client("logs", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _log_group(service_name: str) -> str:
    return f"/aws/lambda/anomaly-demo-{service_name}"


@tool(name="get_recent_errors")
def get_recent_errors(service_name: str, minutes: int = 15) -> dict:
    """Fetch recent error and degraded log entries for a service.

    Queries CloudWatch Logs Insights for entries where
    status = 'error' or status = 'degraded' within the last N minutes.

    Args:
        service_name: Lambda service name, e.g. 'order', 'payment'.
        minutes: How far back to look (default 15).

    Returns:
        Dict with the service name and a list of error entries,
        each containing timestamp, status, message, dependency,
        error_type, and latency_ms.
    """
    client = _get_logs_client()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (minutes * 60 * 1000)

    query = (
        "fields @timestamp, @message "
        "| filter @message like /\"status\":\\s*\"(error|degraded)\"/ "
        "| sort @timestamp desc "
        "| limit 50"
    )

    try:
        start_resp = client.start_query(
            logGroupName=_log_group(service_name),
            startTime=start_ms,
            endTime=end_ms,
            queryString=query,
        )
        query_id = start_resp["queryId"]

        status = "Running"
        results = []
        for _ in range(30):
            resp = client.get_query_results(queryId=query_id)
            status = resp["status"]
            if status in ("Complete", "Failed", "Cancelled"):
                results = resp.get("results", [])
                break
            time.sleep(1)

        entries = []
        import json
        for row in results:
            msg_field = next((f["value"] for f in row if f["field"] == "@message"), None)
            if msg_field:
                try:
                    parsed = json.loads(msg_field)
                    entries.append({
                        "timestamp": parsed.get("timestamp"),
                        "status": parsed.get("status"),
                        "message": parsed.get("message"),
                        "dependency": parsed.get("dependency"),
                        "error_type": parsed.get("error_type"),
                        "latency_ms": parsed.get("latency_ms"),
                    })
                except json.JSONDecodeError:
                    entries.append({"raw": msg_field})

        return {"service": service_name, "minutes": minutes, "errors": entries}

    except client.exceptions.ResourceNotFoundException:
        return {"service": service_name, "error": f"Log group {_log_group(service_name)} not found."}
    except Exception as e:
        return {"service": service_name, "error": str(e)}


@tool(name="get_latency_stats")
def get_latency_stats(service_name: str, minutes: int = 15) -> dict:
    """Get latency statistics for a service's recent log entries.

    Queries CloudWatch Logs Insights for avg, p50, p90, p99, and max
    latency across all structured log entries in the time window.

    Args:
        service_name: Lambda service name.
        minutes: How far back to look (default 15).

    Returns:
        Dict with latency statistics in milliseconds.
    """
    client = _get_logs_client()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (minutes * 60 * 1000)

    query = (
        "fields @message "
        "| filter @message like /\"latency_ms\"/ "
        "| parse @message '\"latency_ms\": *}' as lat_raw "
        "| parse @message '\"latency_ms\": *, ' as lat_raw2 "
        "| stats avg(coalesce(lat_raw, lat_raw2)) as avg_ms, "
        "  min(coalesce(lat_raw, lat_raw2)) as min_ms, "
        "  max(coalesce(lat_raw, lat_raw2)) as max_ms, "
        "  pct(coalesce(lat_raw, lat_raw2), 50) as p50_ms, "
        "  pct(coalesce(lat_raw, lat_raw2), 90) as p90_ms, "
        "  pct(coalesce(lat_raw, lat_raw2), 99) as p99_ms, "
        "  count(*) as total_entries"
    )

    try:
        start_resp = client.start_query(
            logGroupName=_log_group(service_name),
            startTime=start_ms,
            endTime=end_ms,
            queryString=query,
        )
        query_id = start_resp["queryId"]

        for _ in range(30):
            resp = client.get_query_results(queryId=query_id)
            if resp["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(1)

        results = resp.get("results", [])
        if results:
            stats = {f["field"]: f["value"] for f in results[0]}
            return {"service": service_name, "minutes": minutes, "latency": stats}
        return {"service": service_name, "minutes": minutes, "latency": {}}

    except client.exceptions.ResourceNotFoundException:
        return {"service": service_name, "error": f"Log group {_log_group(service_name)} not found."}
    except Exception as e:
        return {"service": service_name, "error": str(e)}


@tool(name="get_dependency_errors")
def get_dependency_errors(dependency_name: str, minutes: int = 15) -> dict:
    """Search ALL service log groups for errors mentioning a specific dependency.

    This is useful when the agent knows which infrastructure component
    failed (e.g. 'pgpri', 'redis2') and wants to see which services
    are reporting problems with it.

    Args:
        dependency_name: Dependency key as logged by the services,
            e.g. 'pgpri', 'redis2', 'kafka', 'sendgrid'.
        minutes: How far back to look (default 15).

    Returns:
        Dict mapping service names to their error entries for
        that dependency.
    """
    services = [
        "order", "payment", "cart", "inventory", "shipping",
        "user", "search", "notification", "pricing", "recommendation",
    ]

    client = _get_logs_client()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (minutes * 60 * 1000)

    log_groups = []
    for svc in services:
        try:
            client.describe_log_groups(logGroupNamePrefix=_log_group(svc))
            log_groups.append(_log_group(svc))
        except Exception:
            continue

    if not log_groups:
        return {"dependency": dependency_name, "error": "No log groups found."}

    query = (
        f"fields @timestamp, @message, @logStream "
        f"| filter @message like /\"{dependency_name}\"/ "
        f"| filter @message like /\"(error|degraded)\"/ "
        f"| sort @timestamp desc "
        f"| limit 50"
    )

    try:
        start_resp = client.start_query(
            logGroupNames=log_groups,
            startTime=start_ms,
            endTime=end_ms,
            queryString=query,
        )
        query_id = start_resp["queryId"]

        for _ in range(30):
            resp = client.get_query_results(queryId=query_id)
            if resp["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(1)

        import json
        by_service = {}
        for row in resp.get("results", []):
            msg_field = next((f["value"] for f in row if f["field"] == "@message"), None)
            log_stream = next((f["value"] for f in row if f["field"] == "@logStream"), "")
            if msg_field:
                try:
                    parsed = json.loads(msg_field)
                    svc = parsed.get("service", "unknown")
                    by_service.setdefault(svc, []).append({
                        "timestamp": parsed.get("timestamp"),
                        "status": parsed.get("status"),
                        "message": parsed.get("message"),
                        "error_type": parsed.get("error_type"),
                        "latency_ms": parsed.get("latency_ms"),
                    })
                except json.JSONDecodeError:
                    pass

        return {"dependency": dependency_name, "minutes": minutes, "affected_services": by_service}

    except Exception as e:
        return {"dependency": dependency_name, "error": str(e)}
