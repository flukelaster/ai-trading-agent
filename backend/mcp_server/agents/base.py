"""
Base agent — shared agent loop using Anthropic Messages API with tool_use.

All specialist agents and the orchestrator use run_agent_loop().
"""

import asyncio
import json
import os
import time
from typing import Any

from anthropic import AsyncAnthropic
from loguru import logger


# ─── Model Constants ─────────────────────────────────────────────────────────

MODEL_ORCHESTRATOR = "claude-sonnet-4-20250514"
MODEL_SPECIALIST = "claude-haiku-4-5-20251001"


def _get_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY", "")


# ─── Shared Agent Loop ──────────────────────────────────────────────────────

async def run_agent_loop(
    system_prompt: str,
    user_message: str,
    tools: list[dict[str, Any]] | None = None,
    tool_names: list[str] | None = None,
    model: str = MODEL_SPECIALIST,
    max_turns: int = 15,
    timeout: int = 120,
    **kwargs,
) -> dict:
    """Run an agent loop using Anthropic Messages API.

    Args:
        system_prompt: Agent's system prompt
        user_message: The task/query
        tools: Tool definitions (JSON schema format for Messages API)
        tool_names: Alternative: filter tools from TOOLS by name
        model: Claude model to use
        max_turns: Maximum turns
        timeout: Timeout in seconds

    Returns:
        Dict with response, tool_calls, turns, duration_s.
    """
    api_key = _get_api_key()
    if not api_key:
        return {"response": "No ANTHROPIC_API_KEY configured", "tool_calls": [], "turns": 0}

    # Resolve tools by name if needed
    if tools is None and tool_names is not None:
        from mcp_server.agent_config import get_tools_by_name
        tools = get_tools_by_name(tool_names)

    client = AsyncAnthropic(api_key=api_key)
    messages: list[dict] = [{"role": "user", "content": user_message}]
    tool_calls_made: list[dict] = []
    start_time = time.time()

    for turn in range(max_turns):
        if time.time() - start_time > timeout:
            logger.warning(f"Agent timeout after {timeout}s")
            break

        try:
            kwargs_api: dict = {
                "model": model,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": messages,
            }
            if tools:
                kwargs_api["tools"] = tools

            response = await client.messages.create(**kwargs_api)
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return {
                "response": f"API error: {e}",
                "tool_calls": tool_calls_made,
                "turns": turn,
                "error": str(e),
            }

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Done — no more tool calls
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
                from mcp_server.agent_config import execute_tool
                logger.info(f"[Agent] Tool: {block.name}")
                result_str = await execute_tool(block.name, block.input)

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
