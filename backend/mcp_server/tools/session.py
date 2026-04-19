"""
MCP tools for session memory management.

Stores and retrieves agent context across job executions using Redis.
Allows the agent to "remember" insights, preferences, and lessons learned.

Keys use TTL for automatic cleanup:
- session:agent:{symbol}:{date} — daily context (24h TTL)
- session:agent:global — cross-session learnings (7d TTL)
"""

import json
from datetime import UTC, datetime

import redis.asyncio as redis_lib

_redis: redis_lib.Redis | None = None

_SESSION_TTL_DAILY = 86400  # 24 hours
_SESSION_TTL_GLOBAL = 86400 * 7  # 7 days


def init_session(redis_client: redis_lib.Redis) -> None:
    """Initialize session storage with a Redis client."""
    global _redis
    _redis = redis_client


def _require_redis():
    if not _redis:
        raise RuntimeError("Session storage not initialized — call init_session(redis) first")


def _daily_key(symbol: str) -> str:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"session:agent:{symbol}:{date}"


def _global_key() -> str:
    return "session:agent:global"


async def save_context(symbol: str, context: dict) -> dict:
    """Save session context for a symbol (today's session).

    Context is merged with existing data (not replaced).
    Use this to store insights learned during analysis.

    Args:
        symbol: Trading symbol
        context: Dict of context data to save (merged with existing)

    Returns:
        Confirmation dict.
    """
    _require_redis()
    key = _daily_key(symbol)

    # Merge with existing context
    existing = await _redis.get(key)
    if existing:
        try:
            current = json.loads(existing)
        except json.JSONDecodeError:
            current = {}
    else:
        current = {}

    current.update(context)
    current["last_updated"] = datetime.now(UTC).isoformat()

    await _redis.set(key, json.dumps(current, default=str), ex=_SESSION_TTL_DAILY)
    return {"saved": True, "symbol": symbol, "keys": list(current.keys())}


async def get_context(symbol: str) -> dict:
    """Retrieve today's session context for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        Dict with stored context, or empty dict if no context exists.
    """
    _require_redis()
    key = _daily_key(symbol)
    data = await _redis.get(key)
    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return {}
    return {}


async def save_learning(learning: str, category: str = "general") -> dict:
    """Save a cross-session learning that persists for 7 days.

    Use this for insights that should inform future sessions:
    - "GOLD tends to reverse at 2500 resistance"
    - "NFP day: reduce position size by 50%"
    - "EMA crossover works better in trending regime"

    Args:
        learning: The insight text
        category: Category (general, strategy, risk, pattern)

    Returns:
        Confirmation dict.
    """
    _require_redis()
    key = _global_key()

    existing = await _redis.get(key)
    if existing:
        try:
            learnings = json.loads(existing)
        except json.JSONDecodeError:
            learnings = {"entries": []}
    else:
        learnings = {"entries": []}

    learnings["entries"].append(
        {
            "text": learning,
            "category": category,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    # Keep only last 50 learnings
    learnings["entries"] = learnings["entries"][-50:]

    await _redis.set(key, json.dumps(learnings, default=str), ex=_SESSION_TTL_GLOBAL)
    return {"saved": True, "total_learnings": len(learnings["entries"])}


async def get_learnings(category: str | None = None) -> dict:
    """Retrieve cross-session learnings.

    Args:
        category: Optional filter by category

    Returns:
        Dict with list of learning entries.
    """
    _require_redis()
    key = _global_key()
    data = await _redis.get(key)

    if not data:
        return {"entries": [], "count": 0}

    try:
        learnings = json.loads(data)
    except json.JSONDecodeError:
        return {"entries": [], "count": 0}

    entries = learnings.get("entries", [])
    if category:
        entries = [e for e in entries if e.get("category") == category]

    return {"entries": entries, "count": len(entries)}


async def clear_context(symbol: str) -> dict:
    """Clear today's session context for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        Confirmation dict.
    """
    _require_redis()
    key = _daily_key(symbol)
    await _redis.delete(key)
    return {"cleared": True, "symbol": symbol}
