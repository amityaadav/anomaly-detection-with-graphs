"""Inventory Service Lambda — manages stock levels and reservations.

Dependencies: PostgreSQL (critical), Kafka (async), Redis Cluster 2 (cache),
Auth, Config.
"""

import json
import time

import redis
import psycopg2

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Handle inventory operations (check/reserve/update)."""
    start = time.time()
    action = event.get("action", "check")
    product_id = event.get("product_id", "unknown")

    try:
        if action == "reserve":
            result = _reserve_stock(product_id, event.get("quantity", 1))
        elif action == "update":
            result = _update_stock(product_id, event.get("quantity", 0))
        else:
            result = _check_stock(product_id)

        _update_cache(product_id, result)
        _publish_kafka(product_id, action)

        latency = (time.time() - start) * 1000
        log_event("success", f"Inventory {action} for {product_id}", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"product_id": product_id, "stock": result}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"Inventory operation failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _check_stock(product_id: str) -> int:
    """Check stock level — try cache first, fall back to PG."""
    t = time.time()

    if not is_failure_active("redis2-failure"):
        try:
            host = get_param("redis-host")
            r = redis.Redis(host=host, port=6379, socket_timeout=5)
            cached = r.get(f"stock:{product_id}")
            if cached:
                latency = (time.time() - t) * 1000
                log_event("success", f"Cache hit stock:{product_id}", latency_ms=latency, dependency="redis2")
                return int(cached)
        except redis.ConnectionError as e:
            log_event("degraded", f"Redis unavailable: {e}", latency_ms=(time.time() - t) * 1000, dependency="redis2")

    return _read_postgres(product_id)


def _read_postgres(product_id: str) -> int:
    """Read stock level from PostgreSQL."""
    t = time.time()

    if is_failure_active("pgpri-failure"):
        log_event(
            "error", "FATAL: too many connections for role postgres",
            latency_ms=(time.time() - t) * 1000, dependency="pgpri", error_type="connection_pool_exhausted",
        )
        raise ConnectionError("PostgreSQL: connection pool exhausted")

    try:
        host = get_param("pg-endpoint")
        conn = psycopg2.connect(
            host=host, port=5432, dbname="demo", user="postgres",
            password=get_param("pg-password"), connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute("SELECT stock FROM inventory WHERE product_id = %s", (product_id,))
        row = cur.fetchone()
        conn.close()
        stock = row[0] if row else 100
        latency = (time.time() - t) * 1000
        log_event("success", f"PG read stock for {product_id}: {stock}", latency_ms=latency, dependency="pgpri")
        return stock
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG read failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _reserve_stock(product_id: str, quantity: int) -> int:
    """Reserve stock by decrementing in PostgreSQL."""
    t = time.time()

    if is_failure_active("pgpri-failure"):
        log_event(
            "error", "FATAL: too many connections for role postgres",
            latency_ms=(time.time() - t) * 1000, dependency="pgpri", error_type="connection_pool_exhausted",
        )
        raise ConnectionError("PostgreSQL: connection pool exhausted")

    try:
        host = get_param("pg-endpoint")
        conn = psycopg2.connect(
            host=host, port=5432, dbname="demo", user="postgres",
            password=get_param("pg-password"), connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute(
            "UPDATE inventory SET stock = stock - %s WHERE product_id = %s AND stock >= %s RETURNING stock",
            (quantity, product_id, quantity),
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        if not row:
            raise ValueError(f"Insufficient stock for {product_id}")
        latency = (time.time() - t) * 1000
        log_event("success", f"Reserved {quantity} of {product_id}, remaining: {row[0]}", latency_ms=latency, dependency="pgpri")
        return row[0]
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG reserve failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _update_stock(product_id: str, quantity: int) -> int:
    """Set stock level in PostgreSQL."""
    t = time.time()

    if is_failure_active("pgpri-failure"):
        log_event(
            "error", "FATAL: too many connections for role postgres",
            latency_ms=(time.time() - t) * 1000, dependency="pgpri", error_type="connection_pool_exhausted",
        )
        raise ConnectionError("PostgreSQL: connection pool exhausted")

    try:
        host = get_param("pg-endpoint")
        conn = psycopg2.connect(
            host=host, port=5432, dbname="demo", user="postgres",
            password=get_param("pg-password"), connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO inventory (product_id, stock) VALUES (%s, %s) ON CONFLICT (product_id) DO UPDATE SET stock = %s RETURNING stock",
            (product_id, quantity, quantity),
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        latency = (time.time() - t) * 1000
        log_event("success", f"PG set stock {product_id} = {row[0]}", latency_ms=latency, dependency="pgpri")
        return row[0]
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG write failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _update_cache(product_id: str, stock: int) -> None:
    """Update stock level in Redis cache."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event("degraded", "Skipping cache update — Redis unavailable", latency_ms=0, dependency="redis2")
        return

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.setex(f"stock:{product_id}", 300, str(stock))
        latency = (time.time() - t) * 1000
        log_event("success", f"Cache updated stock:{product_id} = {stock}", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError:
        log_event("degraded", "Cache update failed — Redis unavailable", latency_ms=(time.time() - t) * 1000, dependency="redis2")


def _publish_kafka(product_id: str, action: str) -> None:
    """Publish inventory event to Kafka (simulated)."""
    t = time.time()

    if is_failure_active("kafka-failure"):
        log_event(
            "degraded", "Kafka producer timeout — event queued locally",
            latency_ms=(time.time() - t) * 1000, dependency="kafka", error_type="producer_timeout",
        )
        return

    log_event("success", f"Published inventory.{action} for {product_id}", latency_ms=(time.time() - t) * 1000, dependency="kafka")
