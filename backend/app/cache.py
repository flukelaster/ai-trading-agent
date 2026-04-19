"""
Redis Response Cache — lightweight caching for API responses.
"""

import json
from collections.abc import Callable
from typing import Any

import redis.asyncio as redis_lib
from loguru import logger


async def cached(
    redis_client: redis_lib.Redis,
    key: str,
    ttl_seconds: int,
    fetch_fn: Callable,
) -> Any:
    """
    Check Redis for cached response. On miss, call fetch_fn and cache result.

    Args:
        redis_client: Redis client instance.
        key: Cache key (e.g., "cache:perf:GOLD:30").
        ttl_seconds: Time-to-live in seconds.
        fetch_fn: Async callable that produces the response data.

    Returns:
        The cached or freshly fetched data (as a dict/list).
    """
    try:
        raw = await redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass  # cache miss or error — proceed to fetch

    # Cache miss — fetch fresh data
    data = await fetch_fn()

    # Store in cache (fire-and-forget)
    try:
        await redis_client.set(key, json.dumps(data, default=str), ex=ttl_seconds)
    except Exception as e:
        logger.debug(f"Cache set failed for {key}: {e}")

    return data


async def invalidate(redis_client: redis_lib.Redis, pattern: str):
    """Delete all cache keys matching a pattern (e.g., 'cache:perf:*')."""
    try:
        keys = []
        async for key in redis_client.scan_iter(pattern):
            keys.append(key)
        if keys:
            await redis_client.delete(*keys)
    except Exception as e:
        logger.debug(f"Cache invalidation failed for {pattern}: {e}")
