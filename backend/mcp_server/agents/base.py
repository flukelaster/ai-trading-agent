"""
Base agent — shared agent loop using Claude Agent SDK (Max subscription).

All specialist agents and the orchestrator use run_agent_loop().
"""

from typing import Any

from mcp_server.sdk_client import sdk_agent_loop

# ─── Model Constants ─────────────────────────────────────────────────────────

MODEL_ORCHESTRATOR = "claude-sonnet-4-20250514"
MODEL_SPECIALIST = "claude-haiku-4-5-20251001"


# ─── Shared Agent Loop ──────────────────────────────────────────────────────


async def run_agent_loop(
    system_prompt: str,
    user_message: str,
    tools: list[dict[str, Any]] | None = None,
    tool_names: list[str] | None = None,
    model: str = MODEL_SPECIALIST,
    max_turns: int = 15,
    timeout: int = 120,
    agent_id: str = "unknown",
    **kwargs,
) -> dict:
    """Run an agent loop using Claude Agent SDK."""
    return await sdk_agent_loop(
        prompt=user_message,
        system_prompt=system_prompt,
        model=model,
        allowed_tools=tool_names,
        max_turns=max_turns,
        timeout=timeout,
        agent_id=agent_id,
    )
