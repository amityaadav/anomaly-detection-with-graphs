"""Recommendation Service Lambda — product recommendations via ML.

Dependencies: Elasticsearch (critical), Redis Cluster 2 (cache),
ML Model Service (critical), Config, Feature Flags.
"""

import json
import time

import redis

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Get product recommendations for a user or product."""
    start = time.time()
    user_id = event.get("user_id", "anonymous")
    product_id = event.get("product_id")
    limit = event.get("limit", 5)

    try:
        cache_key = f"recs:{user_id}:{product_id or 'home'}"
        cached = _check_cache(cache_key)
        if cached:
            return {"statusCode": 200, "body": json.dumps(cached)}

        candidates = _search_elasticsearch(user_id, product_id)
        scored = _score_with_ml(candidates, user_id)
        recommendations = sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]

        result = {"user_id": user_id, "recommendations": recommendations}
        _write_cache(cache_key, result)

        latency = (time.time() - start) * 1000
        log_event("success", f"Recommendations for {user_id}: {len(recommendations)} items", latency_ms=latency)

        return {"statusCode": 200, "body": json.dumps(result)}

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"Recommendations failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _check_cache(cache_key: str) -> dict | None:
    """Check Redis cache for cached recommendations."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event("degraded", "Redis unavailable, skipping cache", latency_ms=0, dependency="redis2")
        return None

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        cached = r.get(cache_key)
        if cached:
            latency = (time.time() - t) * 1000
            log_event("success", f"Cache hit {cache_key}", latency_ms=latency, dependency="redis2")
            return json.loads(cached)
        return None
    except redis.ConnectionError:
        log_event("degraded", "Redis connection failed, skipping cache", latency_ms=(time.time() - t) * 1000, dependency="redis2")
        return None


def _search_elasticsearch(user_id: str, product_id: str | None) -> list:
    """Query Elasticsearch for recommendation candidates (simulated).

    In production this would query the Elasticsearch cluster for
    similar products based on collaborative filtering embeddings.
    """
    t = time.time()

    candidates = [
        {"product_id": f"rec-{i}", "name": f"Recommended Product #{i}", "category": "electronics"}
        for i in range(10)
    ]

    latency = (time.time() - t) * 1000
    context = f"product {product_id}" if product_id else f"user {user_id}"
    log_event("success", f"Elasticsearch candidates for {context}: {len(candidates)}", latency_ms=latency, dependency="elastic")
    return candidates


def _score_with_ml(candidates: list, user_id: str) -> list:
    """Score candidates with ML Model Service (simulated).

    In production this calls the ML model service to rank candidates
    using a trained recommendation model.
    """
    t = time.time()

    scored = []
    for i, candidate in enumerate(candidates):
        candidate["score"] = round(0.95 - i * 0.08, 2)
        scored.append(candidate)

    latency = (time.time() - t) * 1000
    log_event("success", f"ML scoring for {user_id}: {len(scored)} candidates scored", latency_ms=latency, dependency="mlmodel")
    return scored


def _write_cache(cache_key: str, result: dict) -> None:
    """Cache recommendations in Redis."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event("degraded", "Skipping cache write — Redis unavailable", latency_ms=0, dependency="redis2")
        return

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.setex(cache_key, 600, json.dumps(result))
        latency = (time.time() - t) * 1000
        log_event("success", f"Cached {cache_key}", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError:
        log_event("degraded", "Cache write failed — Redis unavailable", latency_ms=(time.time() - t) * 1000, dependency="redis2")
