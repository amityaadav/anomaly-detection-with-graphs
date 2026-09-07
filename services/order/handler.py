"""Order Service Lambda — creates orders with real dependency calls.

Dependencies: PostgreSQL (write), Redis Cluster 2 (cache), Payment Service
(sync), Inventory Service (sync), Kafka (async), Notification Service (async).
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
    """Process an order creation request."""
    start = time.time()
    order_id = str(uuid.uuid4())[:8]

    try:
        # Step 1: Write order to Redis cache
        _write_redis(order_id, event)

        # Step 2: Insert into PostgreSQL
        _write_postgres(order_id, event)

        # Step 3: Call Payment Service (sync)
        _call_payment(order_id, event)

        # Step 4: Call Inventory Service (sync)
        _call_inventory(order_id, event)

        # Step 5: Publish to Kafka (async — simulated via structured log)
        _publish_kafka(order_id)

        latency = (time.time() - start) * 1000
        log_event("success", f"Order {order_id} created", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"order_id": order_id, "status": "created"}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event(
            "error",
            f"Order creation failed: {str(e)}",
            latency_ms=latency,
            error_type=type(e).__name__,
        )
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


def _write_redis(order_id: str, event: dict) -> None:
    """Write order data to Redis Cluster 2 (cache layer)."""
    t = time.time()

    # Check failure injection
    if is_failure_active("redis2-failure"):
        latency = (time.time() - t) * 1000
        log_event(
            "timeout",
            "Redis write timeout after 5000ms",
            latency_ms=5000,
            dependency="redis2",
            error_type="connection_timeout",
        )
        raise TimeoutError("Redis Cluster 2: connection timeout")

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.setex(f"order:{order_id}", 3600, json.dumps(event))
        latency = (time.time() - t) * 1000
        log_event("success", f"Redis write order:{order_id}", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError as e:
        latency = (time.time() - t) * 1000
        log_event(
            "error",
            f"Redis connection failed: {e}",
            latency_ms=latency,
            dependency="redis2",
            error_type="connection_refused",
        )
        raise


def _write_postgres(order_id: str, event: dict) -> None:
    """Insert order record into PostgreSQL Primary."""
    t = time.time()

    if is_failure_active("pgpri-failure"):
        latency = (time.time() - t) * 1000
        log_event(
            "error",
            "FATAL: too many connections for role postgres",
            latency_ms=latency,
            dependency="pgpri",
            error_type="connection_pool_exhausted",
        )
        raise ConnectionError("PostgreSQL: connection pool exhausted")

    try:
        host = get_param("pg-endpoint")
        conn = psycopg2.connect(
            host=host, port=5432, dbname="demo", user="postgres",
            password=get_param("pg-password") if not is_failure_active("vault-failure") else "stale-password",
            connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders (id, payload, created_at) VALUES (%s, %s, NOW()) ON CONFLICT DO NOTHING",
            (order_id, json.dumps(event)),
        )
        conn.commit()
        conn.close()
        latency = (time.time() - t) * 1000
        log_event("success", f"PG insert order {order_id}", latency_ms=latency, dependency="pgpri")
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event(
            "error",
            f"PG write failed: {e}",
            latency_ms=latency,
            dependency="pgpri",
            error_type=type(e).__name__,
        )
        raise


def _call_payment(order_id: str, event: dict) -> None:
    """Call Payment Service via HTTP (sync dependency)."""
    t = time.time()
    try:
        # In AWS, this would be the Payment Lambda's function URL or API Gateway endpoint
        payment_url = os.environ.get("PAYMENT_URL", "http://localhost:8001/pay")
        resp = requests.post(
            payment_url,
            json={"order_id": order_id, "amount": event.get("amount", 0)},
            timeout=10,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        log_event("success", f"Payment processed for {order_id}", latency_ms=latency, dependency="payment")
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event(
            "error",
            f"Payment call failed: {e}",
            latency_ms=latency,
            dependency="payment",
            error_type=type(e).__name__,
        )
        raise


def _call_inventory(order_id: str, event: dict) -> None:
    """Call Inventory Service via HTTP (sync dependency)."""
    t = time.time()
    try:
        inv_url = os.environ.get("INVENTORY_URL", "http://localhost:8002/reserve")
        resp = requests.post(
            inv_url,
            json={"order_id": order_id, "items": event.get("items", [])},
            timeout=10,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        log_event("success", f"Inventory reserved for {order_id}", latency_ms=latency, dependency="inventory")
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event(
            "error",
            f"Inventory call failed: {e}",
            latency_ms=latency,
            dependency="inventory",
            error_type=type(e).__name__,
        )
        raise


def _publish_kafka(order_id: str) -> None:
    """Publish order event to Kafka (async — simulated via log for demo)."""
    t = time.time()

    if is_failure_active("kafka-failure"):
        latency = (time.time() - t) * 1000
        log_event(
            "degraded",
            "Kafka producer timeout — event queued locally",
            latency_ms=latency,
            dependency="kafka",
            error_type="producer_timeout",
        )
        return  # Async — doesn't fail the order

    latency = (time.time() - t) * 1000
    log_event(
        "success",
        f"Published order.created event for {order_id}",
        latency_ms=latency,
        dependency="kafka",
    )
