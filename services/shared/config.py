"""Read SSM parameters and Secrets Manager secrets for service configuration.

Caches values for the lifetime of the Lambda execution environment
to minimize API calls (free tier: 10,000 SSM calls/month).
"""

import json
import os
import boto3

_ssm = boto3.client("ssm")
_sm = boto3.client("secretsmanager")
_cache: dict[str, str] = {}
_secret_cache: dict[str, dict] = {}
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/anomaly-demo")

_SECRET_MAPPING: dict[str, tuple[str, str]] = {
    "pg-password": ("anomaly-demo/rds-credentials", "password"),
    "neo4j-password": ("anomaly-demo/neo4j-credentials", "password"),
    "redis-password": ("anomaly-demo/redis-credentials", "password"),
    "ollama-api-key": ("anomaly-demo/ollama-credentials", "api_key"),
}


def get_secret(secret_id: str, key: str) -> str:
    """Get a field from a Secrets Manager secret (cached)."""
    if secret_id not in _secret_cache:
        resp = _sm.get_secret_value(SecretId=secret_id)
        _secret_cache[secret_id] = json.loads(resp["SecretString"])
    return _secret_cache[secret_id][key]


def get_param(name: str, use_cache: bool = True) -> str:
    """Get a config parameter from env vars, Secrets Manager, or SSM.

    Args:
        name: Parameter name without the prefix (e.g. 'redis-host').
        use_cache: Whether to use the in-memory cache.
    """
    env_key = name.upper().replace("-", "_").replace("/", "_")
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val

    if name in _SECRET_MAPPING:
        secret_id, key = _SECRET_MAPPING[name]
        return get_secret(secret_id, key)

    full_name = f"{SSM_PREFIX}/{name}"

    if use_cache and full_name in _cache:
        return _cache[full_name]

    resp = _ssm.get_parameter(Name=full_name)
    value = resp["Parameter"]["Value"]
    _cache[full_name] = value
    return value


def is_failure_active(flag_name: str) -> bool:
    """Check if a failure injection flag is enabled.

    Failure flags are never cached — always read fresh so injection
    takes effect immediately.
    """
    try:
        value = get_param(f"flags/{flag_name}", use_cache=False)
        return value.lower() == "true"
    except Exception:
        return False


def clear_cache() -> None:
    """Clear cached parameters (useful for testing)."""
    _cache.clear()
    _secret_cache.clear()
