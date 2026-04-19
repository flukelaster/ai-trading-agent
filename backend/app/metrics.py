"""
Lightweight metrics — Redis-backed timing and counters.
No external dependencies (Prometheus, OpenTelemetry, etc.).
"""

import time
from contextlib import asynccontextmanager

import redis.asyncio as redis_lib
from loguru import logger


class Metrics:
    """Simple metrics singleton using Redis for storage."""

    def __init__(self, redis_client: redis_lib.Redis):
        self.redis = redis_client
        self._prefix = "metrics:"

    async def record_timing(self, name: str, duration_ms: float):
        """Record a timing measurement."""
        key = f"{self._prefix}timing:{name}"
        try:
            await self.redis.lpush(key, str(duration_ms))
            await self.redis.ltrim(key, 0, 999)  # keep last 1000
            await self.redis.expire(key, 86400)  # 24h TTL
        except Exception:
            pass

    async def increment_counter(self, name: str, amount: int = 1):
        """Increment a daily counter."""
        key = f"{self._prefix}counter:{name}"
        try:
            await self.redis.incrby(key, amount)
            await self.redis.expire(key, 86400)
        except Exception:
            pass

    async def get_summary(self) -> dict:
        """Get summary of all metrics."""
        summary = {"timings": {}, "counters": {}}
        try:
            # Scan for timing keys
            async for key in self.redis.scan_iter(f"{self._prefix}timing:*"):
                name = (
                    key.decode().replace(f"{self._prefix}timing:", "")
                    if isinstance(key, bytes)
                    else key.replace(f"{self._prefix}timing:", "")
                )
                values = await self.redis.lrange(key, 0, -1)
                if values:
                    floats = sorted([float(v) for v in values])
                    n = len(floats)
                    summary["timings"][name] = {
                        "count": n,
                        "p50": floats[n // 2] if n else 0,
                        "p95": floats[int(n * 0.95)] if n >= 20 else floats[-1] if n else 0,
                        "p99": floats[int(n * 0.99)] if n >= 100 else floats[-1] if n else 0,
                        "avg": sum(floats) / n if n else 0,
                    }

            # Scan for counter keys
            async for key in self.redis.scan_iter(f"{self._prefix}counter:*"):
                name = (
                    key.decode().replace(f"{self._prefix}counter:", "")
                    if isinstance(key, bytes)
                    else key.replace(f"{self._prefix}counter:", "")
                )
                val = await self.redis.get(key)
                summary["counters"][name] = int(val) if val else 0
        except Exception as e:
            logger.debug(f"Metrics summary error: {e}")

        return summary

    @asynccontextmanager
    async def measure(self, name: str):
        """Context manager to measure execution time."""
        start = time.monotonic()
        try:
            yield
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            await self.record_timing(name, round(duration_ms, 1))


# Global instance — set in main.py lifespan
_metrics: Metrics | None = None


def get_metrics() -> Metrics | None:
    return _metrics


def set_metrics(m: Metrics):
    global _metrics
    _metrics = m
