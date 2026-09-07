"""Read SSM parameters for service configuration and failure flags.

Caches values for the lifetime of the Lambda execution environment
to minimize SSM API calls (free tier: 10,000 calls/month).
"""

import os
import boto3

_ssm = boto3.client("ssm")
_cache: dict[str, str] = {}
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/anomaly-demo")


def get_param(name: str, use_cache: bool = True) -> str:
    """Get an SSM parameter value.

    Args:
        name: Parameter name without the prefix (e.g. 'redis-host').
        use_cache: Whether to use the in-memory cache.
    """
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
