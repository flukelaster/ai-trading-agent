"""
Agent configuration — entry points for AI trading agent.

Tools are served via MCP server (server.py), dispatched by Claude Agent SDK.
"""

import json
from pathlib import Path

from loguru import logger

from mcp_server.agents.base import run_agent_loop, MODEL_ORCHESTRATOR
from mcp_server.guardrails import AGENT_TIMEOUT, MAX_AGENT_TURNS


# ─── System Prompt ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT: str | None = None


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        prompt_path = Path(__file__).parent / "system_prompt.md"
        _SYSTEM_PROMPT = prompt_path.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


# ─── Agent Entry Points ─────────────────────────────────────────────────────

async def run_agent(
    job_type: str,
    job_input: dict | None,
    model: str = MODEL_ORCHESTRATOR,
) -> dict:
    """Run single-agent loop."""
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(job_type, job_input)

    result = await run_agent_loop(
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        max_turns=MAX_AGENT_TURNS,
        timeout=AGENT_TIMEOUT,
    )
    decision = result.get("response", "No decision")

    # Extract strategy name from decision text
    strategy_used = "ai_autonomous"
    for keyword in ["Trend Following", "Mean Reversion", "Breakout", "Momentum", "Hold"]:
        if keyword.lower() in decision.lower():
            strategy_used = keyword.lower().replace(" ", "_")
            break

    return {
        "decision": decision,
        "strategy_used": strategy_used,
        "turns": result.get("turns", 0),
        "tool_calls": result.get("tool_calls", []),
        "duration_s": result.get("duration_s", 0),
    }


async def run_multi_agent(
    job_type: str,
    job_input: dict | None,
) -> dict:
    """Run multi-agent pipeline."""
    from mcp_server.agents.orchestrator import run_multi_agent as _run
    return await _run(job_type, job_input)


def _build_user_message(job_type: str, job_input: dict | None) -> str:
    input_str = json.dumps(job_input, default=str) if job_input else "{}"
    if job_type == "candle_analysis":
        symbol = (job_input or {}).get("symbol", "GOLD")
        timeframe = (job_input or {}).get("timeframe", "M15")
        return f"A new {timeframe} candle has closed for {symbol}. Analyze and decide whether to trade.\n\nJob input: {input_str}"
    elif job_type == "manual_analysis":
        symbol = (job_input or {}).get("symbol", "GOLD")
        return f"Manual analysis requested for {symbol}. Provide thorough analysis with recommendation.\n\nJob input: {input_str}"
    elif job_type == "weekly_review":
        return f"Perform a weekly trading review.\n\nJob input: {input_str}"
    else:
        return f"Job type: {job_type}\nInput: {input_str}"
