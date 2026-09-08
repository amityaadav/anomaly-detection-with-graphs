"""Notification Service Lambda — dispatches email, SMS, and push notifications.

Dependencies: Kafka (critical), RabbitMQ (degraded fallback), SendGrid (critical),
SMS Provider (critical), MongoDB (degraded), Redis Cluster 1 (cache), Config.
"""

import json
import time
import os

import redis
import requests

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Process a notification request."""
    start = time.time()
    notification_type = event.get("type", "email")
    recipient = event.get("recipient", "unknown")
    template_id = event.get("template_id", "default")

    try:
        _consume_kafka(event)
        template = _load_template(template_id)

        if notification_type in ("email", "all"):
            _send_email(recipient, template, event)
        if notification_type in ("sms", "all"):
            _send_sms(recipient, template, event)
        if notification_type in ("push", "all"):
            _send_push(recipient, template, event)

        _cache_status(recipient, notification_type)

        latency = (time.time() - start) * 1000
        log_event("success", f"Notification ({notification_type}) sent to {recipient}", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"recipient": recipient, "type": notification_type, "status": "sent"}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"Notification failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _consume_kafka(event: dict) -> None:
    """Consume notification event from Kafka (simulated)."""
    t = time.time()

    if is_failure_active("kafka-failure"):
        log_event(
            "error", "Kafka consumer group lag > 10000, falling back to RabbitMQ",
            latency_ms=(time.time() - t) * 1000, dependency="kafka", error_type="consumer_lag",
        )
        _fallback_rabbit(event)
        return

    log_event("success", f"Consumed event from Kafka: {event.get('type', 'unknown')}", latency_ms=(time.time() - t) * 1000, dependency="kafka")


def _fallback_rabbit(event: dict) -> None:
    """Fall back to RabbitMQ when Kafka is degraded (simulated)."""
    t = time.time()
    log_event("degraded", "Processing via RabbitMQ fallback", latency_ms=(time.time() - t) * 1000, dependency="rabbit")


def _load_template(template_id: str) -> dict:
    """Load notification template from MongoDB (simulated)."""
    t = time.time()

    template = {
        "id": template_id,
        "subject": f"Notification: {template_id}",
        "body": f"Template body for {template_id}",
    }

    log_event("success", f"Loaded template {template_id} from MongoDB", latency_ms=(time.time() - t) * 1000, dependency="mongo")
    return template


def _send_email(recipient: str, template: dict, event: dict) -> None:
    """Send email via SendGrid (simulated external)."""
    t = time.time()

    if is_failure_active("dns-failure"):
        log_event(
            "error", "DNS resolution failed for api.sendgrid.com",
            latency_ms=30000, dependency="sendgrid", error_type="dns_resolution_failed",
        )
        raise ConnectionError("DNS: NXDOMAIN for api.sendgrid.com")

    try:
        sendgrid_url = os.environ.get("SENDGRID_URL", "http://localhost:8012/send")
        resp = requests.post(
            sendgrid_url,
            json={"to": recipient, "subject": template["subject"], "body": template["body"]},
            timeout=10,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        log_event("success", f"Email sent to {recipient}", latency_ms=latency, dependency="sendgrid")
    except requests.ConnectionError:
        latency = (time.time() - t) * 1000
        log_event("success", f"Email to {recipient} simulated", latency_ms=latency, dependency="sendgrid")


def _send_sms(recipient: str, template: dict, event: dict) -> None:
    """Send SMS via SMS Provider (simulated external)."""
    t = time.time()

    if is_failure_active("dns-failure"):
        log_event(
            "error", "DNS resolution failed for api.smsprovider.com",
            latency_ms=30000, dependency="sms", error_type="dns_resolution_failed",
        )
        raise ConnectionError("DNS: NXDOMAIN for api.smsprovider.com")

    try:
        sms_url = os.environ.get("SMS_URL", "http://localhost:8013/send")
        resp = requests.post(
            sms_url,
            json={"to": recipient, "message": template["body"]},
            timeout=10,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        log_event("success", f"SMS sent to {recipient}", latency_ms=latency, dependency="sms")
    except requests.ConnectionError:
        latency = (time.time() - t) * 1000
        log_event("success", f"SMS to {recipient} simulated", latency_ms=latency, dependency="sms")


def _send_push(recipient: str, template: dict, event: dict) -> None:
    """Send push notification (simulated)."""
    t = time.time()
    log_event("success", f"Push notification sent to {recipient}", latency_ms=(time.time() - t) * 1000, dependency="push")


def _cache_status(recipient: str, notification_type: str) -> None:
    """Cache notification status in Redis (redis1)."""
    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.setex(f"notif:{recipient}:{notification_type}", 3600, "sent")
    except redis.ConnectionError:
        log_event("degraded", "Cache write failed for notification status", latency_ms=0, dependency="redis1")
