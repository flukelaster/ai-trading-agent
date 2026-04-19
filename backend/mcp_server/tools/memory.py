"""
MCP tools for layered agent memory — mid-term (30d) and long-term (permanent).

Allows agents to persist insights beyond the 7-day Redis learning window.
Backed by PostgreSQL via the backend API.
"""

import httpx

from mcp_server.tools import auth_headers
from mcp_server.tools import backend_url as _backend_url


async def save_memory(
    summary: str,
    category: str = "pattern",
    symbol: str | None = None,
    evidence: dict | None = None,
) -> dict:
    """Save an insight to mid-term memory (30 days, promotable to permanent).

    Use this for data-backed patterns that should persist beyond the current session:
    - "GOLD drops 0.5% after NFP when USD strengthens"
    - "EMA crossover win rate drops below 30% in ranging regime"
    - "Reducing lot size during London/NY overlap improves risk-reward"

    Duplicate insights are automatically merged (hit_count incremented).

    Args:
        summary: Concise, actionable insight text
        category: One of: pattern, strategy, risk, regime, correlation
        symbol: Trading symbol (None for global insights)
        evidence: Supporting data (trade IDs, dates, statistics)

    Returns:
        Dict with action (created/merged), id, and confidence.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_backend_url()}/api/memory",
                json={
                    "summary": summary,
                    "category": category,
                    "symbol": symbol,
                    "evidence": evidence,
                    "source": "reflector",
                },
                headers=auth_headers(),
            )
            if resp.status_code in (200, 201):
                return resp.json()
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return {"error": str(e)}


async def get_memories(
    symbol: str | None = None,
    category: str | None = None,
    tier: str | None = None,
    limit: int = 20,
) -> dict:
    """Recall stored memories, sorted by confidence.

    Use this at the start of each analysis to recall what you've learned.
    Returns both mid-term and long-term memories by default.

    Args:
        symbol: Filter by symbol (also includes global memories)
        category: Filter by category (pattern/strategy/risk/regime/correlation)
        tier: Filter by tier (mid/long). None returns both.
        limit: Maximum memories to return (default 20)

    Returns:
        Dict with memories list and count.
    """
    try:
        params: dict = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if category:
            params["category"] = category
        if tier:
            params["tier"] = tier

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_backend_url()}/api/memory",
                params=params,
                headers=auth_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            return {"memories": [], "count": 0, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"memories": [], "count": 0, "error": str(e)}


async def validate_memory(
    memory_id: int,
    hit: bool,
) -> dict:
    """Validate whether a stored memory's prediction matched reality.

    Call this after checking recent trade outcomes against stored patterns.
    Memories with high hit rates get promoted to long-term (permanent).
    Memories with low hit rates eventually expire.

    Args:
        memory_id: The memory ID to validate
        hit: True if the pattern held, False if it didn't

    Returns:
        Dict with updated hit_count, miss_count, and confidence.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{_backend_url()}/api/memory/{memory_id}/validate",
                json={"hit": hit},
                headers=auth_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return {"error": str(e)}
