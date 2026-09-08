"""SNS trigger Lambda — receives CloudWatch alarm events and invokes the agent.

This Lambda is subscribed to the anomaly-demo-alerts SNS topic.
When a CloudWatch alarm fires, SNS delivers the alarm payload here.
The handler parses the SNS message, extracts the alarm details, and
runs the Strands triage agent to produce an incident report.

Path: agent/trigger_lambda/handler.py
"""

import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import run_triage


def lambda_handler(event, context):
    """Handle incoming SNS notification from a CloudWatch alarm.

    The event structure from SNS looks like:
      event["Records"][0]["Sns"]["Message"] -> JSON string of the alarm

    The alarm JSON has fields like:
      AlarmName, AlarmDescription, NewStateValue, Trigger.MetricName,
      Trigger.Namespace, etc.
    """
    start = time.time()

    try:
        sns_records = event.get("Records", [])
        if not sns_records:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No SNS records in event"}),
            }

        sns_message = sns_records[0].get("Sns", {}).get("Message", "{}")
        alarm_data = json.loads(sns_message)

        alarm_name = alarm_data.get("AlarmName", "unknown")
        trigger = alarm_data.get("Trigger", {})

        service = _extract_service_name(alarm_name, trigger)

        alarm_payload = {
            "alarm_name": alarm_name,
            "service": service,
            "description": alarm_data.get("AlarmDescription", ""),
            "metric": trigger.get("MetricName", "unknown"),
            "state": alarm_data.get("NewStateValue", "ALARM"),
        }

        report = run_triage(alarm_payload)

        latency = (time.time() - start) * 1000
        print(json.dumps({
            "status": "success",
            "alarm": alarm_name,
            "service": service,
            "latency_ms": round(latency, 2),
            "report_length": len(report),
        }))

        return {
            "statusCode": 200,
            "body": json.dumps({
                "alarm": alarm_name,
                "service": service,
                "report": report,
            }),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        print(json.dumps({
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "latency_ms": round(latency, 2),
        }))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


def _extract_service_name(alarm_name: str, trigger: dict) -> str:
    """Best-effort extraction of the service name from the alarm.

    Tries the Trigger.Dimensions first (Lambda function name), then
    falls back to parsing the alarm name which follows the pattern
    'anomaly-demo-<service>-<metric>'.
    """
    dimensions = trigger.get("Dimensions", [])
    for dim in dimensions:
        if dim.get("name") == "FunctionName":
            fn_name = dim.get("value", "")
            if fn_name.startswith("anomaly-demo-"):
                return fn_name.replace("anomaly-demo-", "")
            return fn_name

    if alarm_name.startswith("anomaly-demo-"):
        parts = alarm_name.replace("anomaly-demo-", "").split("-")
        if parts:
            return parts[0]

    return "unknown"
