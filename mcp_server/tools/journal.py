"""MCP tools for decision journaling — audit trail for agent reasoning."""

from datetime import datetime, timezone

import httpx

from mcp_server.tools import backend_url as _backend_url


async def log_decision(
    symbol: str,
    decision: str,
    reasoning: str,
    confidence: float | None = None,
    indicators: dict | None = None,
) -> dict:
    """Log a trading decision with full reasoning.

    This creates an audit trail that can be reviewed later to understand
    why the agent made specific decisions. Every trade MUST be logged.

    Args:
        symbol: Trading symbol
        decision: What was decided ("BUY 0.05", "HOLD", "SELL 0.03", etc.)
        reasoning: Full reasoning text explaining the decision
        confidence: Optional confidence score (0.0-1.0)
        indicators: Optional dict of indicator values at decision time

    Returns:
        Dict confirming the log entry was created.
    """
    entry = {
        "action": "agent_decision",
        "actor": "agent",
        "resource": f"trade:{symbol}",
        "detail": {
            "symbol": symbol,
            "decision": decision,
            "reasoning": reasoning,
            "confidence": confidence,
            "indicators": indicators,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Post to audit log via backend API
            resp = await client.post(
                f"{_backend_url()}/api/bot/events",
                json={
                    "event_type": "agent_decision",
                    "symbol": symbol,
                    "detail": entry["detail"],
                },
            )
            # If the events endpoint doesn't accept POSTs, log locally
            if resp.status_code not in (200, 201):
                # Fallback: print to stdout (captured by ProcessRunnerBackend)
                import json
                print(json.dumps({"level": "info", "message": f"[Journal] {decision}", "metadata": entry["detail"]}), flush=True)
    except Exception:
        # If backend is unreachable, log to stdout
        import json
        print(json.dumps({"level": "info", "message": f"[Journal] {decision}", "metadata": entry["detail"]}), flush=True)

    return {"logged": True, "symbol": symbol, "decision": decision}


async def log_reasoning(thought_process: str) -> dict:
    """Log agent's internal reasoning/thought process.

    Use this to record the agent's thought chain for later review.
    This is separate from trade decisions — it captures the "thinking" phase.

    Args:
        thought_process: The agent's reasoning text

    Returns:
        Confirmation dict.
    """
    import json
    print(json.dumps({
        "level": "info",
        "message": f"[Reasoning] {thought_process[:200]}",
        "metadata": {"full_text": thought_process},
    }), flush=True)
    return {"logged": True, "length": len(thought_process)}
