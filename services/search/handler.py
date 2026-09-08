"""Search Service Lambda — product search with caching.

Dependencies: Elasticsearch (critical), Redis Cluster 2 (cache), Config.
"""

import json
import time
import hashlib

import redis

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Handle product search queries."""
    start = time.time()
    query = event.get("query", "")
    filters = event.get("filters", {})

    try:
        cache_key = _cache_key(query, filters)
        results = _check_cache(cache_key)

        if results is None:
            results = _search_elasticsearch(query, filters)
            _write_cache(cache_key, results)

        latency = (time.time() - start) * 1000
        log_event("success", f"Search '{query}' returned {len(results)} results", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"query": query, "results": results, "count": len(results)}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"Search failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _cache_key(query: str, filters: dict) -> str:
    """Generate a deterministic cache key for the search."""
    raw = json.dumps({"q": query, "f": filters}, sort_keys=True)
    return f"search:{hashlib.md5(raw.encode()).hexdigest()}"


def _check_cache(cache_key: str) -> list | None:
    """Check Redis cache for recent search results."""
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
        latency = (time.time() - t) * 1000
        log_event("success", f"Cache miss {cache_key}", latency_ms=latency, dependency="redis2")
        return None
    except redis.ConnectionError:
        log_event("degraded", "Redis connection failed, skipping cache", latency_ms=(time.time() - t) * 1000, dependency="redis2")
        return None


def _search_elasticsearch(query: str, filters: dict) -> list:
    """Query Elasticsearch for product search (simulated).

    In production this would call the Elasticsearch REST API.
    For the demo, we return synthetic results and log the dependency call.
    """
    t = time.time()

    simulated_results = [
        {"product_id": f"prod-{i}", "name": f"Product matching '{query}' #{i}", "score": round(1.0 - i * 0.1, 2)}
        for i in range(min(5, max(1, len(query))))
    ]

    latency = (time.time() - t) * 1000
    log_event(
        "success",
        f"Elasticsearch query '{query}' with {len(filters)} filters: {len(simulated_results)} hits",
        latency_ms=latency,
        dependency="elastic",
    )
    return simulated_results


def _write_cache(cache_key: str, results: list) -> None:
    """Cache search results in Redis."""
    t = time.time()

    if is_failure_active("redis2-failure"):
        log_event("degraded", "Skipping cache write — Redis unavailable", latency_ms=0, dependency="redis2")
        return

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.setex(cache_key, 120, json.dumps(results))
        latency = (time.time() - t) * 1000
        log_event("success", f"Cached {cache_key} ({len(results)} results)", latency_ms=latency, dependency="redis2")
    except redis.ConnectionError:
        log_event("degraded", "Cache write failed — Redis unavailable", latency_ms=(time.time() - t) * 1000, dependency="redis2")
