"""
Rate limiting — Redis token bucket per (IP, path).

Phase 4 of long-term DB scaling plan. Prevents runaway polling / client bugs
from exhausting DB pool.

Algorithm: token bucket
- Each (IP, path) pair gets `capacity` tokens
- Tokens refill at `refill_rate` per second
- Each request costs 1 token
- If no tokens: return 429 with Retry-After

Implementation uses Redis Lua script for atomic check+decrement.
"""

from __future__ import annotations

import time

import redis.asyncio as redis_lib
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Lua script: atomic token bucket check + decrement
# KEYS[1] = bucket key
# ARGV[1] = capacity (max tokens)
# ARGV[2] = refill_per_sec
# ARGV[3] = now (unix seconds, float)
# ARGV[4] = cost (tokens for this request)
# Returns: {allowed (0|1), remaining, retry_after_seconds}
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  ts = now
end

local delta = math.max(0, now - ts) * refill
tokens = math.min(capacity, tokens + delta)

local allowed = 0
local retry = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry = math.ceil((cost - tokens) / refill)
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, 120)

return {allowed, tokens, retry}
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis token-bucket rate limiter.

    Defaults: 60 requests / 60 seconds per (client IP, path). Bursts allowed up to
    `burst_capacity` (default 2× sustained rate).

    Exempt paths: WebSocket upgrades, /health*, /api/metrics, static assets.
    """

    # Auth endpoints get a tighter bucket to blunt brute-force / credential stuffing.
    AUTH_PATHS: tuple[str, ...] = (
        "/api/auth/login",
        "/api/auth/login/options",
        "/api/auth/login/verify",
        "/api/auth/register/options",
        "/api/auth/register/verify",
    )
    AUTH_PER_MINUTE = 5
    AUTH_BURST = 10

    def __init__(
        self,
        app,
        sustained_per_minute: int = 60,
        burst_capacity: int | None = None,
        exempt_prefixes: tuple[str, ...] = ("/health", "/ws", "/api/metrics"),
    ):
        super().__init__(app)
        self.refill_rate = sustained_per_minute / 60.0  # tokens per second
        self.capacity = burst_capacity if burst_capacity is not None else sustained_per_minute * 2
        self.exempt_prefixes = exempt_prefixes
        self.auth_refill = self.AUTH_PER_MINUTE / 60.0
        self.auth_capacity = self.AUTH_BURST

    def _client_ip(self, request: Request) -> str:
        # Use the rightmost X-Forwarded-For entry — added by the trusted Railway
        # proxy. The leftmost value is client-supplied and spoofable.
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if parts:
                return parts[-1]
        return request.client.host if request.client else "unknown"

    def _identity(self, request: Request) -> str:
        """Identify the requester for rate-limit bucketing.

        Prefers the authenticated subject decoded from the bearer token so a
        single user behind a shared NAT does not absorb a stranger's quota
        (and vice versa). Falls back to the trusted client IP when the request
        is unauthenticated or the token cannot be decoded.

        Explicitly rejects the literal ``__noauth__`` sentinel so a client
        cannot forge ``Authorization: Bearer __noauth__`` and have every
        request bucketed under one shared identity.
        """
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if not token or token == "__noauth__":
                return f"ip:{self._client_ip(request)}"
            try:
                from app.auth import verify_token

                sub = verify_token(token)
                if sub and sub != "__noauth__":
                    return f"u:{sub}"
            except Exception:
                pass
        return f"ip:{self._client_ip(request)}"

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self.exempt_prefixes):
            return await call_next(request)

        redis_client: redis_lib.Redis | None = getattr(request.app.state, "redis", None)
        if redis_client is None:
            # Fail closed for auth endpoints so a Redis outage cannot become an
            # unrestricted brute-force window. Other paths fall through (the
            # service is more useful than degraded protection on read APIs).
            if path in self.AUTH_PATHS:
                return JSONResponse(
                    status_code=503,
                    content={"error": "rate_limiter_unavailable"},
                    headers={"Retry-After": "30"},
                )
            return await call_next(request)

        is_auth_path = path in self.AUTH_PATHS
        capacity = self.auth_capacity if is_auth_path else self.capacity
        refill = self.auth_refill if is_auth_path else self.refill_rate
        # Auth paths bucket by IP because the user is not authenticated yet.
        # Other paths bucket by user when a valid bearer token is present, so
        # one user's burst does not consume a co-located peer's quota.
        if is_auth_path:
            key = f"rl:ip:{self._client_ip(request)}:auth"
        else:
            key = f"rl:{self._identity(request)}:{path}"
        now = time.time()

        try:
            result = await redis_client.eval(
                _TOKEN_BUCKET_LUA,
                1,
                key,
                capacity,
                refill,
                now,
                1,
            )
            allowed = int(result[0]) == 1
            remaining = int(float(result[1]))
            retry_after = int(result[2])
        except Exception as e:
            # Redis hiccup mid-request — fail closed for auth, fail open for
            # everything else. Avoids letting a Redis blip become a brute-force
            # window while keeping read APIs available under partial outage.
            if is_auth_path:
                logger.warning(f"Rate limiter Redis error on auth path (fail-closed): {e!r}")
                return JSONResponse(
                    status_code=503,
                    content={"error": "rate_limiter_unavailable"},
                    headers={"Retry-After": "30"},
                )
            logger.debug(f"Rate limiter Redis error (fail-open): {e}")
            return await call_next(request)

        if not allowed:
            logger.warning(f"rate_limited key={key} path={path} retry_after={retry_after}s")
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "retry_after": retry_after},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(capacity),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
