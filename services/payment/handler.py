"""Payment Service Lambda — processes payments with real dependency calls.

Dependencies: PostgreSQL (write), Stripe (sync external), Kafka (async),
Redis Cluster 2 (cache), Auth, Config, Vault.
"""

import json
import time
import os
import uuid

import redis
import psycopg2
import requests

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Process a payment request."""
    start = time.time()
    payment_id = str(uuid.uuid4())[:8]
    order_id = event.get("order_id", "unknown")

    try:
        _check_duplicate(payment_id, order_id)
        _charge_stripe(payment_id, event)
        _write_postgres(payment_id, event)
        _publish_kafka(payment_id)

        latency = (time.time() - start) * 1000
        log_event("success", f"Payment {payment_id} processed", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"payment_id": payment_id, "status": "processed"}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event(
            "error",
            f"Payment failed: {str(e)}",
            latency_ms=latency,
            error_type=type(e).__name__,
        )
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _check_duplicate(payment_id: str, order_id: str) -> None:
    """Check Redis for duplicate payment (idempotency)."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event(
            "timeout", "Redis read timeout after 5000ms",
            latency_ms=5000, dependency="redis2", error_type="connection_timeout",
        )
        raise TimeoutError("Redis Cluster 2: connection timeout")

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        existing = r.get(f"payment:{order_id}")
        if existing:
            raise ValueError(f"Duplicate payment for order {order_id}")
        r.setex(f"payment:{order_id}", 3600, payment_id)
        latency = (time.time() - t) * 1000
        log_event("success", f"Idempotency check passed for {order_id}", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"Redis connection failed: {e}", latency_ms=latency, dependency="redis2", error_type="connection_refused")
        raise


def _charge_stripe(payment_id: str, event: dict) -> None:
    """Call Stripe for payment processing (simulated external)."""
    t = time.time()

    if is_failure_active("dns-failure"):
        log_event(
            "error", "DNS resolution failed for api.stripe.com",
            latency_ms=30000, dependency="stripe", error_type="dns_resolution_failed",
        )
        raise ConnectionError("DNS: NXDOMAIN for api.stripe.com")

    try:
        stripe_url = os.environ.get("STRIPE_URL", "http://localhost:8010/charge")
        resp = requests.post(
            stripe_url,
            json={"payment_id": payment_id, "amount": event.get("amount", 0), "currency": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        log_event("success", f"Stripe charge {payment_id}: ${event.get('amount', 0)}", latency_ms=latency, dependency="stripe")
    except requests.ConnectionError:
        latency = (time.time() - t) * 1000
        log_event("success", f"Stripe charge simulated for {payment_id}", latency_ms=latency, dependency="stripe")


def _write_postgres(payment_id: str, event: dict) -> None:
    """Write payment transaction to PostgreSQL."""
    t = time.time()

    if is_failure_active("pgpri-failure"):
        log_event(
            "error", "FATAL: too many connections for role postgres",
            latency_ms=(time.time() - t) * 1000, dependency="pgpri", error_type="connection_pool_exhausted",
        )
        raise ConnectionError("PostgreSQL: connection pool exhausted")

    try:
        host = get_param("pg-endpoint")
        password = get_param("pg-password") if not is_failure_active("vault-failure") else "stale-password"
        conn = psycopg2.connect(
            host=host, port=5432, dbname="demo", user="postgres",
            password=password, connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO payments (id, order_id, amount, status, created_at) VALUES (%s, %s, %s, %s, NOW()) ON CONFLICT DO NOTHING",
            (payment_id, event.get("order_id"), event.get("amount", 0), "processed"),
        )
        conn.commit()
        conn.close()
        latency = (time.time() - t) * 1000
        log_event("success", f"PG insert payment {payment_id}", latency_ms=latency, dependency="pgpri")
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG write failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _publish_kafka(payment_id: str) -> None:
    """Publish payment.processed event to Kafka (simulated)."""
    t = time.time()

    if is_failure_active("kafka-failure"):
        log_event(
            "degraded", "Kafka producer timeout — event queued locally",
            latency_ms=(time.time() - t) * 1000, dependency="kafka", error_type="producer_timeout",
        )
        return

    log_event("success", f"Published payment.processed for {payment_id}", latency_ms=(time.time() - t) * 1000, dependency="kafka")
