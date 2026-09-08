"""Pricing Service Lambda — dynamic pricing, discounts, and tax calculation.

Dependencies: PG Read Replica (degraded), Redis Cluster 2 (cache),
Tax API (external degraded), Config, Feature Flags.
"""

import json
import time
import os

import redis
import psycopg2
import requests

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Calculate price for a product."""
    start = time.time()
    product_id = event.get("product_id", "unknown")
    quantity = event.get("quantity", 1)

    try:
        cached = _check_cache(product_id)
        if cached:
            return {
                "statusCode": 200,
                "body": json.dumps(cached),
            }

        base_price = _read_pricing_rules(product_id)
        discount = _check_feature_flags(product_id, base_price)
        tax = _calculate_tax(base_price - discount, event.get("jurisdiction", "US"))
        total = (base_price - discount + tax) * quantity

        result = {
            "product_id": product_id,
            "base_price": base_price,
            "discount": discount,
            "tax": tax,
            "quantity": quantity,
            "total": round(total, 2),
        }

        _write_cache(product_id, result)

        latency = (time.time() - start) * 1000
        log_event("success", f"Price calculated for {product_id}: ${result['total']}", latency_ms=latency)

        return {"statusCode": 200, "body": json.dumps(result)}

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"Pricing failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _check_cache(product_id: str) -> dict | None:
    """Check Redis cache for cached price."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event("degraded", "Redis unavailable, skipping cache", latency_ms=0, dependency="redis2")
        return None

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        cached = r.get(f"price:{product_id}")
        if cached:
            latency = (time.time() - t) * 1000
            log_event("success", f"Cache hit price:{product_id}", latency_ms=latency, dependency="redis2")
            return json.loads(cached)
        return None
    except redis.ConnectionError:
        log_event("degraded", "Redis connection failed, skipping cache", latency_ms=(time.time() - t) * 1000, dependency="redis2")
        return None


def _read_pricing_rules(product_id: str) -> float:
    """Read pricing rules from PG Read Replica (degraded dependency).

    Uses the read replica, not the primary — this is a read-only query.
    Falls back to a default price if the replica is unavailable.
    """
    t = time.time()

    try:
        host = get_param("pg-endpoint")
        conn = psycopg2.connect(
            host=host, port=5432, dbname="demo", user="postgres",
            password=get_param("pg-password"), connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute("SELECT base_price FROM pricing_rules WHERE product_id = %s", (product_id,))
        row = cur.fetchone()
        conn.close()
        price = row[0] if row else 29.99
        latency = (time.time() - t) * 1000
        log_event("success", f"PG read pricing for {product_id}: ${price}", latency_ms=latency, dependency="pgrep")
        return price
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("degraded", f"PG replica unavailable: {e}, using default price", latency_ms=latency, dependency="pgrep")
        return 29.99


def _check_feature_flags(product_id: str, base_price: float) -> float:
    """Check feature flags for active discounts (simulated)."""
    t = time.time()

    discount = 0.0
    log_event("success", f"Feature flag check for {product_id}: discount=${discount}", latency_ms=(time.time() - t) * 1000, dependency="flagsvc")
    return discount


def _calculate_tax(subtotal: float, jurisdiction: str) -> float:
    """Calculate tax via Tax API (simulated external)."""
    t = time.time()

    if is_failure_active("dns-failure"):
        log_event(
            "degraded", "DNS resolution failed for api.tax.com, using default rate",
            latency_ms=100, dependency="taxapi", error_type="dns_resolution_failed",
        )
        return round(subtotal * 0.08, 2)

    try:
        tax_url = os.environ.get("TAX_URL", "http://localhost:8014/calculate")
        resp = requests.post(
            tax_url,
            json={"subtotal": subtotal, "jurisdiction": jurisdiction},
            timeout=5,
        )
        resp.raise_for_status()
        tax = resp.json().get("tax", subtotal * 0.08)
        latency = (time.time() - t) * 1000
        log_event("success", f"Tax calculated: ${tax} for {jurisdiction}", latency_ms=latency, dependency="taxapi")
        return tax
    except Exception:
        latency = (time.time() - t) * 1000
        tax = round(subtotal * 0.08, 2)
        log_event("degraded", f"Tax API unavailable, using default 8%: ${tax}", latency_ms=latency, dependency="taxapi")
        return tax


def _write_cache(product_id: str, result: dict) -> None:
    """Cache computed price in Redis."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event("degraded", "Skipping cache write — Redis unavailable", latency_ms=0, dependency="redis2")
        return

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.setex(f"price:{product_id}", 300, json.dumps(result))
        latency = (time.time() - t) * 1000
        log_event("success", f"Cached price:{product_id}", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError:
        log_event("degraded", "Cache write failed — Redis unavailable", latency_ms=(time.time() - t) * 1000, dependency="redis2")
