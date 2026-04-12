"""MCP tools for market sentiment — queries backend API for cached sentiment."""

import httpx

from mcp_server.tools import backend_url as _backend_url


async def get_latest_sentiment() -> dict:
    """Get the latest AI sentiment analysis.

    Queries the backend API for the most recent sentiment data rather than
    making a separate Anthropic API call. This avoids duplicate token usage
    and leverages the backend's caching/scheduling of sentiment analysis.

    Returns:
        Dict with sentiment label (bullish/bearish/neutral), score, and timestamp.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_backend_url()}/api/ai/sentiment")
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Backend returned {resp.status_code}"}
    except Exception as e:
        return {"error": f"Failed to fetch sentiment: {e}"}


async def get_sentiment_history(days: int = 7) -> dict:
    """Get sentiment analysis history.

    Args:
        days: Number of days of history to fetch

    Returns:
        Dict with list of historical sentiment entries.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_backend_url()}/api/ai/sentiment/history",
                params={"days": days},
            )
            if resp.status_code == 200:
                return {"entries": resp.json()}
            return {"error": f"Backend returned {resp.status_code}"}
    except Exception as e:
        return {"error": f"Failed to fetch sentiment history: {e}"}
