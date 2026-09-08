"""Cart Service Lambda — manages shopping cart state.

Dependencies: Redis Cluster 2 (critical cache), Pricing Service (sync),
Inventory Service (sync), Auth, Config.
"""

import json
import time
import os

import redis
import requests

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Handle cart operations (add/remove/get)."""
    start = time.time()
    user_id = event.get("user_id", "anonymous")
    action = event.get("action", "get")

    try:
        if action == "add":
            _check_inventory(event)
            price = _get_price(event)
            _update_cart(user_id, event, price)
        elif action == "remove":
            _remove_from_cart(user_id, event)
        cart = _get_cart(user_id)

        latency = (time.time() - start) * 1000
        log_event("success", f"Cart {action} for user {user_id}", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"user_id": user_id, "cart": cart}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"Cart operation failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _get_cart(user_id: str) -> dict:
    """Read cart state from Redis (critical dependency)."""
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
        raw = r.get(f"cart:{user_id}")
        latency = (time.time() - t) * 1000
        log_event("success", f"Redis read cart:{user_id}", latency_ms=latency, dependency="redis2")
        return json.loads(raw) if raw else {"items": []}
    except redis.ConnectionError as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"Redis connection failed: {e}", latency_ms=latency, dependency="redis2", error_type="connection_refused")
        raise


def _update_cart(user_id: str, event: dict, price: float) -> None:
    """Add item to cart in Redis."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event(
            "timeout", "Redis write timeout after 5000ms",
            latency_ms=5000, dependency="redis2", error_type="connection_timeout",
        )
        raise TimeoutError("Redis Cluster 2: connection timeout")

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        raw = r.get(f"cart:{user_id}")
        cart = json.loads(raw) if raw else {"items": []}
        cart["items"].append({
            "product_id": event.get("product_id"),
            "quantity": event.get("quantity", 1),
            "price": price,
        })
        r.setex(f"cart:{user_id}", 86400, json.dumps(cart))
        latency = (time.time() - t) * 1000
        log_event("success", f"Redis write cart:{user_id}", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"Redis connection failed: {e}", latency_ms=latency, dependency="redis2", error_type="connection_refused")
        raise


def _remove_from_cart(user_id: str, event: dict) -> None:
    """Remove item from cart in Redis."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event(
            "timeout", "Redis write timeout after 5000ms",
            latency_ms=5000, dependency="redis2", error_type="connection_timeout",
        )
        raise TimeoutError("Redis Cluster 2: connection timeout")

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        raw = r.get(f"cart:{user_id}")
        cart = json.loads(raw) if raw else {"items": []}
        product_id = event.get("product_id")
        cart["items"] = [i for i in cart["items"] if i.get("product_id") != product_id]
        r.setex(f"cart:{user_id}", 86400, json.dumps(cart))
        latency = (time.time() - t) * 1000
        log_event("success", f"Removed {product_id} from cart:{user_id}", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"Redis connection failed: {e}", latency_ms=latency, dependency="redis2", error_type="connection_refused")
        raise


def _get_price(event: dict) -> float:
    """Call Pricing Service to get current price (degraded dependency)."""
    t = time.time()
    try:
        pricing_url = os.environ.get("PRICING_URL", "http://localhost:8008/price")
        resp = requests.post(
            pricing_url,
            json={"product_id": event.get("product_id")},
            timeout=5,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        log_event("success", f"Price fetched for {event.get('product_id')}", latency_ms=latency, dependency="pricing")
        return resp.json().get("price", 9.99)
    except Exception:
        latency = (time.time() - t) * 1000
        log_event("degraded", "Pricing unavailable, using cached price", latency_ms=latency, dependency="pricing")
        return event.get("price", 9.99)


def _check_inventory(event: dict) -> None:
    """Call Inventory Service to check availability (degraded dependency)."""
    t = time.time()
    try:
        inv_url = os.environ.get("INVENTORY_URL", "http://localhost:8002/check")
        resp = requests.post(
            inv_url,
            json={"product_id": event.get("product_id"), "quantity": event.get("quantity", 1)},
            timeout=5,
        )
        resp.raise_for_status()
        latency = (time.time() - t) * 1000
        log_event("success", f"Inventory available for {event.get('product_id')}", latency_ms=latency, dependency="inventory")
    except Exception:
        latency = (time.time() - t) * 1000
        log_event("degraded", "Inventory check skipped — service unavailable", latency_ms=latency, dependency="inventory")
