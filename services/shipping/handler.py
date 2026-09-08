"""Shipping Service Lambda — generates labels and tracks shipments.

Dependencies: Carrier API (critical external), PostgreSQL (critical),
Kafka (async), Auth, Config, Vault.
"""

import json
import time
import os
import uuid

import psycopg2
import requests

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Create a shipment for an order."""
    start = time.time()
    shipment_id = str(uuid.uuid4())[:8]
    order_id = event.get("order_id", "unknown")

    try:
        rate = _get_carrier_rate(shipment_id, event)
        _write_postgres(shipment_id, order_id, rate)
        _publish_kafka(shipment_id)

        latency = (time.time() - start) * 1000
        log_event("success", f"Shipment {shipment_id} created", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"shipment_id": shipment_id, "rate": rate, "status": "label_created"}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"Shipping failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _get_carrier_rate(shipment_id: str, event: dict) -> float:
    """Get shipping rate from Carrier API (simulated external)."""
    t = time.time()

    if is_failure_active("dns-failure"):
        log_event(
            "error", "DNS resolution failed for api.carrier.com",
            latency_ms=30000, dependency="carrier", error_type="dns_resolution_failed",
        )
        raise ConnectionError("DNS: NXDOMAIN for api.carrier.com")

    try:
        carrier_url = os.environ.get("CARRIER_URL", "http://localhost:8011/rate")
        resp = requests.post(
            carrier_url,
            json={"shipment_id": shipment_id, "destination": event.get("address", {}), "weight": event.get("weight", 1.0)},
            timeout=10,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        rate = resp.json().get("rate", 12.99)
        log_event("success", f"Carrier rate for {shipment_id}: ${rate}", latency_ms=latency, dependency="carrier")
        return rate
    except requests.ConnectionError:
        latency = (time.time() - t) * 1000
        rate = 12.99
        log_event("success", f"Carrier rate simulated for {shipment_id}: ${rate}", latency_ms=latency, dependency="carrier")
        return rate


def _write_postgres(shipment_id: str, order_id: str, rate: float) -> None:
    """Write shipment record to PostgreSQL."""
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
            "INSERT INTO shipments (id, order_id, rate, status, created_at) VALUES (%s, %s, %s, %s, NOW()) ON CONFLICT DO NOTHING",
            (shipment_id, order_id, rate, "label_created"),
        )
        conn.commit()
        conn.close()
        latency = (time.time() - t) * 1000
        log_event("success", f"PG insert shipment {shipment_id}", latency_ms=latency, dependency="pgpri")
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG write failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _publish_kafka(shipment_id: str) -> None:
    """Publish shipment.created event to Kafka (simulated)."""
    t = time.time()

    if is_failure_active("kafka-failure"):
        log_event(
            "degraded", "Kafka producer timeout — event queued locally",
            latency_ms=(time.time() - t) * 1000, dependency="kafka", error_type="producer_timeout",
        )
        return

    log_event("success", f"Published shipment.created for {shipment_id}", latency_ms=(time.time() - t) * 1000, dependency="kafka")
