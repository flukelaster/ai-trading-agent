"""
Base agent — shared agentic loop used by all specialist agents and the orchestrator.

Provides a reusable `run_agent_loop()` that sends messages to Claude with a subset
of tools, executes tool calls, and returns the final response.
"""

import asyncio
import json
import os
import time
from typing import Any

from anthropic import AsyncAnthropic
from loguru import logger

from mcp_server.agent_config import _execute_tool, TOOLS as ALL_TOOLS
from mcp_server.guardrails import AGENT_TIMEOUT


# ─── Model Constants ─────────────────────────────────────────────────────────

MODEL_ORCHESTRATOR = "claude-sonnet-4-20250514"
MODEL_SPECIALIST = "claude-haiku-4-5-20251001"


# ─── Shared Agent Loop ──────────────────────────────────────────────────────

async def run_agent_loop(
    system_prompt: str,
    user_message: str,
    tools: list[dict[str, Any]],
    model: str = MODEL_SPECIALIST,
    max_turns: int = 15,
    timeout: int = 120,
    oauth_token: str | None = None,
) -> dict:
    """Run a single agent loop with the given tools and prompt.

    Args:
        system_prompt: Agent's system prompt (role definition)
        user_message: The task/query for the agent
        tools: List of tool definitions (subset of ALL_TOOLS)
        model: Claude model to use
        max_turns: Maximum conversation turns
        timeout: Timeout in seconds
        oauth_token: OAuth token (defaults to env var)

    Returns:
        Dict with response text, tool calls made, and metadata.
    """
    token = oauth_token or os.environ.get("CLAUDE_OAUTH_TOKEN")
    if not token:
        return {"response": "No OAuth token available", "tool_calls": [], "turns": 0}

    client = AsyncAnthropic(api_key=token)
    messages: list[dict] = [{"role": "user", "content": user_message}]
    tool_calls_made: list[dict] = []
    start_time = time.time()

    for turn in range(max_turns):
        if time.time() - start_time > timeout:
            logger.warning(f"Agent timeout after {timeout}s")
            break

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=tools if tools else None,
                messages=messages,
            )
        except Exception as e:
            logger.error(f"Claude API error in agent loop: {e}")
            return {
                "response": f"API error: {e}",
                "tool_calls": tool_calls_made,
                "turns": turn,
                "error": str(e),
            }

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # If model is done (no more tool calls)
        if response.stop_reason == "end_turn":
            final_text = ""
            for block in assistant_content:
                if hasattr(block, "text"):
                    final_text += block.text
            return {
                "response": final_text,
                "tool_calls": tool_calls_made,
                "turns": turn + 1,
                "duration_s": round(time.time() - start_time, 1),
            }

        # Execute tool calls
        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                logger.info(f"[Specialist] Tool: {block.name}")
                result_str = await _execute_tool(block.name, block.input)

                tool_calls_made.append({
                    "tool": block.name,
                    "input": block.input,
                    "output_preview": result_str[:200],
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return {
        "response": "Max turns reached",
        "tool_calls": tool_calls_made,
        "turns": max_turns,
        "duration_s": round(time.time() - start_time, 1),
    }


def filter_tools(tool_names: list[str]) -> list[dict[str, Any]]:
    """Filter ALL_TOOLS to only include the named tools."""
    return [t for t in ALL_TOOLS if t["name"] in tool_names]
