"""
SDK Client — wraps Claude Agent SDK query() for trading bot use cases.

Uses Max subscription via CLAUDE_CODE_OAUTH_TOKEN (no API key needed).
Two entry points:
  - sdk_complete(): simple prompt → text (sentiment analysis)
  - sdk_agent_loop(): multi-turn with MCP tools (trading agent)
"""

import os
import sys
import time
from typing import Any

from loguru import logger

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
)
from claude_agent_sdk.types import TextBlock, ToolUseBlock


# MCP server name used in server.py — must match for allowed_tools prefix
MCP_SERVER_NAME = "trading-agent-tools"

# Path to the MCP server entry point (relative to backend/)
_MCP_SERVER_MODULE = "mcp_server.server"


def _get_mcp_server_config() -> dict:
    """Build MCP stdio server config pointing to our FastMCP server."""
    python_exe = sys.executable
    env = {
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379"),
        "MT5_BRIDGE_URL": os.environ.get("MT5_BRIDGE_URL", "http://localhost:8001"),
    }
    return {
        MCP_SERVER_NAME: {
            "command": python_exe,
            "args": ["-m", _MCP_SERVER_MODULE],
            "env": env,
        }
    }


def _mcp_tool_name(tool_name: str) -> str:
    """Convert short tool name to MCP-qualified name."""
    return f"mcp__{MCP_SERVER_NAME}__{tool_name}"


async def sdk_complete(
    prompt: str,
    system_prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_turns: int = 1,
) -> str | None:
    """Simple prompt → text response. No tools. For sentiment analysis."""
    try:
        text_parts: list[str] = []
        stderr_lines: list[str] = []

        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                system_prompt=system_prompt,
                model=model,
                max_turns=max_turns,
                permission_mode="bypassPermissions",
                stderr=lambda line: stderr_lines.append(line),
            ),
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)

        result = "".join(text_parts)
        if result:
            logger.info(f"SDK complete: {len(result)} chars")
            return result

        logger.warning(f"SDK complete: empty response. stderr: {''.join(stderr_lines[-5:])}")
        return None
    except Exception as e:
        logger.error(f"SDK complete error: {e}")
        if stderr_lines:
            logger.error(f"SDK stderr: {''.join(stderr_lines[-10:])}")
        return None


async def sdk_agent_loop(
    prompt: str,
    system_prompt: str,
    model: str = "claude-sonnet-4-20250514",
    allowed_tools: list[str] | None = None,
    max_turns: int = 15,
    timeout: int = 120,
) -> dict[str, Any]:
    """Multi-turn agent loop with MCP trading tools.

    Returns dict matching run_agent_loop format:
        {response, tool_calls, turns, duration_s}
    """
    start_time = time.time()
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    turns = 0
    cost_usd: float | None = None
    stderr_lines: list[str] = []

    try:
        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
            permission_mode="bypassPermissions",
            mcp_servers=_get_mcp_server_config(),
            stderr=lambda line: stderr_lines.append(line),
        )

        # Filter tools if specified
        if allowed_tools:
            options.allowed_tools = [_mcp_tool_name(t) for t in allowed_tools]

        async for msg in query(prompt=prompt, options=options):
            # Check timeout
            if time.time() - start_time > timeout:
                logger.warning(f"SDK agent timeout after {timeout}s")
                break

            if isinstance(msg, AssistantMessage):
                turns += 1
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_calls.append({
                            "tool": block.name,
                            "input": block.input,
                        })
                        logger.info(f"[Agent] Tool: {block.name}")

            elif isinstance(msg, ResultMessage):
                cost_usd = getattr(msg, "cost_usd", None) or getattr(msg, "costUsd", None)

        response = "".join(text_parts)
        duration = round(time.time() - start_time, 1)

        logger.info(f"SDK agent: {turns} turns, {len(tool_calls)} tools, {duration}s")

        return {
            "response": response or "No response",
            "tool_calls": tool_calls,
            "turns": turns,
            "duration_s": duration,
            "cost_usd": cost_usd,
        }

    except Exception as e:
        logger.error(f"SDK agent error: {e}")
        # Log all available error details
        if stderr_lines:
            logger.error(f"SDK stderr: {''.join(stderr_lines[-10:])}")
        if hasattr(e, "error_output"):
            logger.error(f"SDK error_output: {e.error_output}")
        if hasattr(e, "__cause__") and e.__cause__:
            logger.error(f"SDK cause: {e.__cause__}")
        logger.error(f"SDK error type: {type(e).__name__}, attrs: {vars(e) if hasattr(e, '__dict__') else 'N/A'}")
        return {
            "response": f"Agent error: {e}",
            "tool_calls": tool_calls,
            "turns": turns,
            "duration_s": round(time.time() - start_time, 1),
            "error": str(e),
        }
