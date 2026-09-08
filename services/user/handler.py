"""User/Account Service Lambda — manages user profiles and preferences.

Dependencies: PostgreSQL (critical), Redis Cluster 1 (cache), Config, Vault.
"""

import json
import time

import redis
import psycopg2

from shared.config import get_param, is_failure_active
from shared.logger import log_event


def lambda_handler(event, context):
    """Handle user operations (get/create/update)."""
    start = time.time()
    action = event.get("action", "get")
    user_id = event.get("user_id", "unknown")

    try:
        if action == "create":
            result = _create_user(user_id, event)
        elif action == "update":
            result = _update_user(user_id, event)
            _invalidate_cache(user_id)
        else:
            result = _get_user(user_id)

        latency = (time.time() - start) * 1000
        log_event("success", f"User {action} for {user_id}", latency_ms=latency)

        return {
            "statusCode": 200,
            "body": json.dumps({"user_id": user_id, "profile": result}),
        }

    except Exception as e:
        latency = (time.time() - start) * 1000
        log_event("error", f"User operation failed: {str(e)}", latency_ms=latency, error_type=type(e).__name__)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _get_user(user_id: str) -> dict:
    """Get user profile — try cache first, fall back to PG."""
    t = time.time()

    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        cached = r.get(f"user:{user_id}")
        if cached:
            latency = (time.time() - t) * 1000
            log_event("success", f"Cache hit user:{user_id}", latency_ms=latency, dependency="redis1")
            return json.loads(cached)
    except redis.ConnectionError:
        log_event("degraded", "Redis1 unavailable, falling back to PG", latency_ms=(time.time() - t) * 1000, dependency="redis1")

    profile = _read_postgres(user_id)
    _cache_user(user_id, profile)
    return profile


def _read_postgres(user_id: str) -> dict:
    """Read user profile from PostgreSQL."""
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
        cur.execute("SELECT name, email, preferences FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            profile = {"name": row[0], "email": row[1], "preferences": row[2]}
        else:
            profile = {"name": "Unknown", "email": "", "preferences": "{}"}
        latency = (time.time() - t) * 1000
        log_event("success", f"PG read user {user_id}", latency_ms=latency, dependency="pgpri")
        return profile
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG read failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _create_user(user_id: str, event: dict) -> dict:
    """Create user in PostgreSQL."""
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
            "INSERT INTO users (id, name, email, preferences, created_at) VALUES (%s, %s, %s, %s, NOW()) ON CONFLICT DO NOTHING",
            (user_id, event.get("name", ""), event.get("email", ""), json.dumps(event.get("preferences", {}))),
        )
        conn.commit()
        conn.close()
        profile = {"name": event.get("name"), "email": event.get("email"), "preferences": event.get("preferences", {})}
        latency = (time.time() - t) * 1000
        log_event("success", f"PG insert user {user_id}", latency_ms=latency, dependency="pgpri")
        _cache_user(user_id, profile)
        return profile
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG write failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _update_user(user_id: str, event: dict) -> dict:
    """Update user profile in PostgreSQL."""
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
            "UPDATE users SET name = COALESCE(%s, name), email = COALESCE(%s, email) WHERE id = %s",
            (event.get("name"), event.get("email"), user_id),
        )
        conn.commit()
        conn.close()
        latency = (time.time() - t) * 1000
        log_event("success", f"PG update user {user_id}", latency_ms=latency, dependency="pgpri")
        return _read_postgres(user_id)
    except Exception as e:
        latency = (time.time() - t) * 1000
        log_event("error", f"PG write failed: {e}", latency_ms=latency, dependency="pgpri", error_type=type(e).__name__)
        raise


def _cache_user(user_id: str, profile: dict) -> None:
    """Cache user profile in Redis (redis1)."""
    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.setex(f"user:{user_id}", 1800, json.dumps(profile))
    except redis.ConnectionError:
        log_event("degraded", f"Cache write failed for user:{user_id}", latency_ms=0, dependency="redis1")


def _invalidate_cache(user_id: str) -> None:
    """Invalidate cached user profile."""
    try:
        host = get_param("redis-host")
        r = redis.Redis(host=host, port=6379, socket_timeout=5)
        r.delete(f"user:{user_id}")
    except redis.ConnectionError:
        pass
